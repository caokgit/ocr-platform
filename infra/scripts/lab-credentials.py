#!/usr/bin/env python3
"""Create the data path's credentials as cluster Secrets in lab-data, once: never printed, never in Git.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I infra/scripts/lab-credentials.py           # create the missing
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I infra/scripts/lab-credentials.py --check   # list, change nothing

Spec: docs/specs/data-path.md#layout
A Secret that exists is left as it is, so a rerun never changes a password a running service holds. The values
go from this process to kubectl's stdin; only Secret names are printed.
"""

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(ROOT / ".toolchain" / "bin" / "kubectl")
NAMESPACE = "lab-data"
ROLES = ["archive", "debezium", "spark"]  # managed roles of the Cluster lab-pg (infra/argocd/lab-data/postgres.yaml)


def kubectl(*args, stdin=None):
    return subprocess.run([KUBECTL, *args], input=stdin, capture_output=True, text=True)


def exists(kind, name, namespace=None):
    ns = ["-n", namespace] if namespace else []
    return kubectl("get", kind, name, *ns, "-o", "name").returncode == 0


def secret(name, data, type_="Opaque", labels=None):
    return {
        "apiVersion": "v1", "kind": "Secret", "type": type_,
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": labels or {}},
        "data": {k: base64.b64encode(v.encode()).decode() for k, v in data.items()},
    }


def wanted():
    """Every Secret the data path needs, with freshly generated values (used only for the missing ones)."""
    out = [secret(f"lab-pg-{role}", {"username": role, "password": secrets.token_urlsafe(24)},
                  "kubernetes.io/basic-auth", {"cnpg.io/reload": "true"}) for role in ROLES]
    access, key = "lab" + secrets.token_hex(8), secrets.token_urlsafe(30)
    s3_config = {"identities": [{"name": "lab", "credentials": [{"accessKey": access, "secretKey": key}],
                                 "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
    out.append(secret("seaweedfs-s3-config", {"seaweedfs_s3_config": json.dumps(s3_config)}))
    out.append(secret("lab-s3", {"AWS_ACCESS_KEY_ID": access, "AWS_SECRET_ACCESS_KEY": key}))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="list which Secrets exist, change nothing")
    args = ap.parse_args()
    if not os.environ.get("KUBECONFIG"):
        sys.exit("Set KUBECONFIG=$PWD/.scratch_kube/config (lab-up writes it).")
    secrets_ = wanted()
    # The S3 pair must be created together, or SeaweedFS and Spark would hold different keys.
    s3_names = {"seaweedfs-s3-config", "lab-s3"}
    have = {s["metadata"]["name"]: exists("secret", s["metadata"]["name"], NAMESPACE) for s in secrets_}
    for name, present in have.items():
        print(f"{name}: {'exists' if present else 'missing'}")
    if args.check:
        return
    if any(have[n] for n in s3_names) and not all(have[n] for n in s3_names):
        sys.exit("Only one of the two S3 Secrets exists; delete it and rerun so both hold the same key.")
    if not exists("namespace", NAMESPACE):
        r = kubectl("create", "namespace", NAMESPACE)
        if r.returncode:
            sys.exit(r.stderr.strip())
        print(f"namespace {NAMESPACE}: created (Argo CD's lab-data app adopts it)")
    for s in secrets_:
        name = s["metadata"]["name"]
        if have[name]:
            continue
        r = kubectl("create", "-f", "-", stdin=json.dumps(s))
        if r.returncode:
            sys.exit(f"{name}: {r.stderr.strip()}")
        print(f"{name}: created")


if __name__ == "__main__":
    main()
