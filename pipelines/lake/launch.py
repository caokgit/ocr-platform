#!/usr/bin/env python3
"""Start a lake job on the box from the laptop: check the box's memory, refresh the code, create the
SparkApplication, follow the driver's log.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/lake/launch.py jars --follow     # once: the jars
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/lake/launch.py smoke --follow    # acceptance B3
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/lake/launch.py stream            # runs until stopped
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/lake/launch.py stop stream       # delete it
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/lake/launch.py reset silver --follow   # drop tables

Spec: docs/specs/data-path.md#spark-and-the-catalog
The code ConfigMap holds jobs/*.py, jars.txt and the schema.sql of the copy archive holds (the newest under data/snapshots/,
or --copy DIR).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KUBECTL = str(ROOT / ".toolchain" / "bin" / "kubectl")
NS = "lab-data"
SPARK_LIMITS_MIB = 1152 + 1920      # driver 512m + 640m overhead, executor 1g + 896m (k8s/sparkapp.yaml)
MARGIN_MIB = 2048                   # left to the AI team on top (docs/specs/data-path.md#box-budget)


def kubectl(*args, stdin=None, check=True):
    r = subprocess.run([KUBECTL, *args], input=stdin, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"kubectl {' '.join(args[:2])}: {r.stderr.strip()}")
    return r.stdout


def available_mib():
    node = kubectl("get", "nodes", "-o", "jsonpath={.items[0].metadata.name}")
    stats = json.loads(kubectl("get", "--raw", f"/api/v1/nodes/{node}/proxy/stats/summary"))
    return stats["node"]["memory"]["availableBytes"] // 2**20


def stamped(manifest):
    """The commit stamp (docs/specs/data-path.md#layout): HEAD, and whether this folder, the code a run sends, has changes."""
    git = ["git", "-C", str(HERE)]
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True)
    changes = subprocess.run([*git, "status", "--porcelain", "--", "."], capture_output=True, text=True)
    if head.returncode or changes.returncode:
        sys.exit(f"git: {(head.stderr or changes.stderr).strip()}")
    commit, dirty = head.stdout.strip(), "true" if changes.stdout.strip() else "false"
    note = commit[:12] + (", with uncommitted changes" if dirty == "true" else "")
    return manifest.replace("GIT_COMMIT", commit).replace("GIT_DIRTY", dirty), note


def refresh_code(copy_dir):
    """The ConfigMap lake-code: the jobs, the jar list, and the schema.sql of the copy (the newest by default)."""
    copy = Path(copy_dir) if copy_dir else sorted((ROOT / "data" / "snapshots").glob("20*"))[-1]
    files = [f"--from-file={p}" for p in sorted((HERE / "jobs").glob("*.py"))]
    files += [f"--from-file={HERE / 'jars.txt'}", f"--from-file={copy / 'schema.sql'}"]
    cm = kubectl("create", "configmap", "lake-code", "-n", NS, *files, "--dry-run=client", "-o", "yaml")
    kubectl("apply", "-f", "-", stdin=cm)
    return copy


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", help="jars, smoke, stream (or gold), or stop")
    ap.add_argument("target", nargs="*", help="with stop: the job to stop; otherwise the job's arguments")
    ap.add_argument("--copy", help="snapshot folder whose schema.sql the jobs read (default: the newest)")
    ap.add_argument("--follow", action="store_true", help="follow the driver's log")
    args = ap.parse_args()
    if not os.environ.get("KUBECONFIG"):
        sys.exit("Set KUBECONFIG=$PWD/.scratch_kube/config and open the tunnel.")
    if args.job == "stop":
        names = [n for n in kubectl("get", "sparkapplications", "-n", NS, "-o", "name").split()
                 if f"/lake-{args.target[0]}-" in n]
        for n in names:
            kubectl("delete", "-n", NS, n, "--cascade=foreground", "--wait=true", "--timeout=180s")
            print(f"{n} deleted")
        return
    if args.job == "jars":
        refresh_code(args.copy)
        name = f"lake-jars-{datetime.datetime.now():%m%d-%H%M%S}"
        job, note = stamped((HERE / "k8s" / "jars-job.yaml").read_text().replace("name: NAME", f"name: {name}"))
        kubectl("create", "-f", "-", stdin=job)
        print(f"job/{name} created (code at {note})")
        if args.follow:
            time.sleep(5)
            subprocess.run([KUBECTL, "wait", "-n", NS, "--for=condition=Ready", "pod", "-l", f"job-name={name}",
                            "--timeout=600s"], capture_output=True)
            subprocess.run([KUBECTL, "logs", "-n", NS, "-f", f"job/{name}"])
        return
    running = [n for n in kubectl("get", "sparkapplications", "-n", NS, "-o",
                                  "jsonpath={range .items[*]}{.metadata.name} {.status.applicationState.state}{\"\\n\"}{end}").splitlines()
               if n.split()[-1:] and n.split()[-1] in ("RUNNING", "SUBMITTED", "PENDING_RERUN", "")]
    if running:
        sys.exit(f"a Spark job is running ({running[0].split()[0]}); never two at once (spec, box budget)")
    free = available_mib()
    need = SPARK_LIMITS_MIB + MARGIN_MIB
    print(f"box memory available: {free} MiB; this job needs {SPARK_LIMITS_MIB} MiB + {MARGIN_MIB} MiB margin")
    if free < need:
        sys.exit("not enough memory on the box now; try later")
    copy = refresh_code(args.copy)
    name = f"lake-{args.job}-{datetime.datetime.now():%m%d-%H%M%S}"
    app, note = stamped((HERE / "k8s" / "sparkapp.yaml").read_text().replace("name: NAME", f"name: {name}").replace(
        "/opt/lab/JOB.py", f"/opt/lab/{args.job}.py\n  arguments: {json.dumps(args.target)}"))
    kubectl("create", "-f", "-", stdin=app)
    print(f"sparkapplication/{name} created (code at {note}, schema from {copy.name})")
    if not args.follow:
        return
    pod = f"{name}-driver"
    for _ in range(120):          # image pull and the jars from Maven take a few minutes the first time
        phase = kubectl("get", "pod", pod, "-n", NS, "-o", "jsonpath={.status.phase}", check=False)
        if phase in ("Running", "Succeeded", "Failed"):
            break
        time.sleep(5)
    subprocess.run([KUBECTL, "logs", "-n", NS, "-f", pod])
    for _ in range(12):       # the operator records the end a few seconds after the log closes
        state = kubectl("get", "sparkapplication", name, "-n", NS, "-o",
                        "jsonpath={.status.applicationState.state}", check=False)
        if state in ("COMPLETED", "FAILED", "SUBMISSION_FAILED"):
            break
        time.sleep(5)
    print(f"sparkapplication/{name}: {state}")


if __name__ == "__main__":
    main()
