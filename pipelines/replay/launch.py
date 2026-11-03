#!/usr/bin/env python3
"""Start the replayer on the box from the laptop: refresh its code, create its Job, follow its log.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/replay/launch.py init --follow
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/replay/launch.py fill [--speedup N] --follow
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/replay/launch.py slice stg:1 --follow
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/replay/launch.py verify --follow

Spec: docs/specs/data-path.md#replay
Every argument after the mode goes to replay.py unchanged (except --follow).
"""

import datetime
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KUBECTL = str(HERE.parents[1] / ".toolchain" / "bin" / "kubectl")
NS = "lab-data"


def kubectl(*args, stdin=None, check=True):
    r = subprocess.run([KUBECTL, *args], input=stdin, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"kubectl {' '.join(args[:2])}: {r.stderr.strip()}")
    return r.stdout


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


def main():
    args = sys.argv[1:]
    follow = "--follow" in args
    args = [a for a in args if a != "--follow"]
    if not args or args[0] not in ("init", "fill", "slice", "verify"):
        sys.exit(__doc__)
    if not os.environ.get("KUBECONFIG"):
        sys.exit("Set KUBECONFIG=$PWD/.scratch_kube/config and open the tunnel.")
    cm = kubectl("create", "configmap", "replay-code", "-n", NS, f"--from-file={HERE / 'replay.py'}",
                 "--dry-run=client", "-o", "yaml")
    kubectl("apply", "-f", "-", stdin=cm)
    name = f"replay-{args[0]}-{datetime.datetime.now():%m%d-%H%M%S}"
    job, note = stamped((HERE / "k8s" / "job.yaml").read_text().replace("name: NAME", f"name: {name}").replace(
        "replay.py ARGS", "replay.py " + " ".join(shlex.quote(a) for a in args)))
    kubectl("create", "-f", "-", stdin=job)
    print(f"job/{name} created (code at {note})")
    if not follow:
        return
    for _ in range(60):       # wait for the pod to start (image pull, pip install)
        phase = kubectl("get", "pods", "-n", NS, "-l", f"job-name={name}", "-o",
                        "jsonpath={.items[0].status.phase}", check=False)
        if phase in ("Running", "Succeeded", "Failed"):
            break
        time.sleep(5)
    subprocess.run([KUBECTL, "logs", "-n", NS, "-f", f"job/{name}"])
    for _ in range(12):       # the Job's status lags its log's end by a few seconds
        status = kubectl("get", "job", name, "-n", NS, "-o",
                         "jsonpath={.status.succeeded}/{.status.failed}", check=False)
        if status.strip("/"):
            break
        time.sleep(5)
    print(f"job/{name}: {'succeeded' if status.startswith('1') else 'failed: ' + status}")


if __name__ == "__main__":
    main()
