#!/usr/bin/env python3
"""Load one snapshot copy into the lab's `archive` database, through a port-forward from the laptop.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/snapshot/load.py data/snapshots/<id>
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/snapshot/load.py --check     # what archive holds

Spec: docs/specs/data-path.md#snapshot (the load), acceptance B2
The copy is checked against its manifest first; schema.sql and every CSV go in one transaction as the role
`archive`; the row counts are compared with the manifest; the copy id is recorded in archive.lab_meta.copy; the
replayer is granted read access. archive holds one copy at a time: a loaded archive is refused (a new copy is
part of the full new fill). The password is read from the cluster Secret into a mode 600 file, never printed.
"""

import argparse
import base64
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snapshot  # noqa: E402  (the copy's own checks)

ROOT = snapshot.ROOT
KUBECTL = str(ROOT / ".toolchain" / "bin" / "kubectl")
NAMESPACE, SERVICE, SECRET, ROLE, DB = "lab-data", "svc/lab-pg-rw", "lab-pg-archive", "archive", "archive"
LOCAL_PORT = 15432
SCRATCH = ROOT / ".scratch_lab"


def kubectl(*args):
    r = subprocess.run([KUBECTL, *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"kubectl {args[0]}: {r.stderr.strip()}")
    return r.stdout


def pgpass():
    """The archive role's password from its Secret into .scratch_lab/pgpass (mode 600); returns the file."""
    SCRATCH.mkdir(mode=0o700, exist_ok=True)
    password = base64.b64decode(kubectl("get", "secret", SECRET, "-n", NAMESPACE,
                                        "-o", "jsonpath={.data.password}")).decode()
    path = SCRATCH / "pgpass"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"127.0.0.1:{LOCAL_PORT}:{DB}:{ROLE}:{password}\n")
    return path


class PortForward:
    """kubectl port-forward for one connection, ready once kubectl prints its "Forwarding from" line. kubectl 1.36
    ends the whole forward when a forwarded connection is reset, as Postgres's side is when psql disconnects, so
    every psql call opens its own (seen 2026-11-01)."""
    def __enter__(self):
        self.p = subprocess.Popen([KUBECTL, "port-forward", "-n", NAMESPACE, SERVICE, f"{LOCAL_PORT}:5432"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = self.p.stdout.readline()
        if not line.startswith("Forwarding from"):
            self.p.kill()
            sys.exit(f"port-forward did not open: {line.strip()}")
        return self

    def __exit__(self, *exc):
        self.p.terminate()
        self.p.wait()


def psql(passfile, sql=None, script=None):
    with PortForward():
        return _psql(passfile, sql, script)


def _psql(passfile, sql=None, script=None):
    env = {**os.environ, "PGPASSFILE": str(passfile), "PGCLIENTENCODING": "UTF8", "PGCONNECT_TIMEOUT": "10"}
    cmd = ["psql", f"host=127.0.0.1 port={LOCAL_PORT} dbname={DB} user={ROLE} sslmode=require",
           "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    cmd += ["-c", sql] if sql else ["-f", "-"]
    r = subprocess.run(cmd, input=script, capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit(f"psql: {r.stderr.strip()}")
    return r.stdout


def loaded(passfile):
    """The copy id archive holds, or None."""
    if not psql(passfile, "SELECT to_regclass('lab_meta.copy')").strip():  # names are resolved before CASE runs
        return None
    return psql(passfile, "SELECT string_agg(copy_id, ',') FROM lab_meta.copy").strip() or None


def load_script(folder, manifest):
    """One transaction: the tables, every CSV, the copy's record, read access for the replayer."""
    copy_id = folder.name
    sources = sorted({f["source"] for f in manifest["files"]})
    script = ["BEGIN;", (folder / "schema.sql").read_text()]
    for f in manifest["files"]:
        script.append(f"\\copy {f['source']}.\"{f['table']}\" FROM '{folder / f['file']}' WITH (FORMAT csv, HEADER)")
    script += [
        "CREATE SCHEMA lab_meta;",
        "CREATE TABLE lab_meta.copy (copy_id text PRIMARY KEY, manifest_sha256 text NOT NULL, "
        "copy_started timestamptz NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now());",
        f"INSERT INTO lab_meta.copy (copy_id, manifest_sha256, copy_started) VALUES ('{copy_id}', "
        f"'{snapshot.sha256(folder / 'manifest.json')}', '{manifest['started']}');",
    ]
    for schema in sources + ["lab_meta"]:
        script += [f"GRANT USAGE ON SCHEMA {schema} TO replayer;",
                   f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO replayer;"]
    script.append("COMMIT;")
    return "\n".join(script) + "\n"


def load(folder):
    folder = Path(folder).resolve()
    manifest, problems = snapshot.check(folder)
    if problems:
        sys.exit("the copy does not match its manifest:\n  " + "\n  ".join(problems))
    copy_id = folder.name
    passfile = pgpass()
    held = loaded(passfile)
    if held:
        sys.exit(f"archive already holds copy {held}; loading another is part of the full new fill")
    t0 = time.time()
    psql(passfile, script=load_script(folder, manifest))
    seconds = time.time() - t0
    counts = "SELECT " + ", ".join(f"(SELECT count(*) FROM {f['source']}.\"{f['table']}\")"
                                   for f in manifest["files"])
    got = [int(x) for x in psql(passfile, counts).strip().split("|")]
    bad = []
    for f, n in zip(manifest["files"], got):
        mark = "ok" if n == f["rows"] else "DIFFERS"
        if n != f["rows"]:
            bad.append(f["file"])
        print(f"{f['source']}.{f['table']}: {n} rows ({mark})")
    print(f"loaded copy {copy_id}: {sum(got):,} rows in {seconds:.0f} s; "
          f"{len(manifest['files']) - len(bad)} of {len(manifest['files'])} tables match the manifest")
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("copy", nargs="?", help="the copy's folder, data/snapshots/<id>")
    ap.add_argument("--check", action="store_true", help="print which copy archive holds, change nothing")
    args = ap.parse_args()
    if not os.environ.get("KUBECONFIG"):
        sys.exit("Set KUBECONFIG=$PWD/.scratch_kube/config (lab-up writes it) and open the tunnel.")
    if args.check:
        print(f"archive holds: {loaded(pgpass()) or 'nothing'}")
    elif args.copy:
        load(args.copy)
    else:
        ap.error("give a copy folder, or --check")


if __name__ == "__main__":
    main()
