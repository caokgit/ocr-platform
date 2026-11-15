#!/usr/bin/env python3
"""Create the lab's credentials as cluster Secrets, once: never printed, never in Git.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I infra/scripts/lab-credentials.py           # create the missing
    KUBECONFIG=$PWD/.scratch_kube/config python3 -I infra/scripts/lab-credentials.py --check   # list, change nothing

Spec: docs/specs/data-path.md#layout (the data path's, in lab-data);
docs/specs/training-platform.md#security-and-tenancy (2b: MLflow's database role and S3 identity, the training
pods' read-only S3 identity, each in its own namespace).
A Secret that exists is left as it is, so a rerun never changes a password a running service holds; a missing S3
identity is added to SeaweedFS's config beside the existing ones (restart SeaweedFS to load it). The values
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


def secret(name, data, type_="Opaque", labels=None, namespace=NAMESPACE):
    return {
        "apiVersion": "v1", "kind": "Secret", "type": type_,
        "metadata": {"name": name, "namespace": namespace, "labels": labels or {}},
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


# 2b: the training platform (docs/specs/training-platform.md#security-and-tenancy)
IDENTITIES = {  # SeaweedFS scopes an identity's actions by bucket
    "mlflow": ("mlflow", "mlflow-s3", ["Read:lab-lake", "Write:lab-lake", "List:lab-lake"]),
    "train": ("ai-team", "train-s3", ["Read:lab-lake", "List:lab-lake"]),
}


def ensure_namespace(ns):
    if not exists("namespace", ns):
        r = kubectl("create", "namespace", ns)
        if r.returncode:
            sys.exit(r.stderr.strip())
        print(f"namespace {ns}: created (Argo CD's lab-ml app adopts it)")


def create(s):
    r = kubectl("create", "-f", "-", stdin=json.dumps(s))
    if r.returncode:
        sys.exit(f"{s['metadata']['name']}: {r.stderr.strip()}")
    print(f"{s['metadata']['namespace']}/{s['metadata']['name']}: created")


def training_platform(check):
    """MLflow's database role (one password in two namespaces) and the two S3 identities."""
    have_role, have_uri = exists("secret", "lab-pg-mlflow", NAMESPACE), exists("secret", "mlflow-db", "mlflow")
    print(f"lab-pg-mlflow: {'exists' if have_role else 'missing'}; mlflow/mlflow-db: {'exists' if have_uri else 'missing'}")
    cfg = json.loads(base64.b64decode(json.loads(kubectl("get", "secret", "seaweedfs-s3-config", "-n", NAMESPACE,
                                                          "-o", "json").stdout)["data"]["seaweedfs_s3_config"]))
    names = {i["name"] for i in cfg["identities"]}
    for ident, (ns, sec, _) in IDENTITIES.items():
        print(f"S3 identity {ident}: {'exists' if ident in names else 'missing'}; {ns}/{sec}: "
              f"{'exists' if exists('secret', sec, ns) else 'missing'}")
    if check:
        return
    if have_role != have_uri:
        sys.exit("Only one of lab-pg-mlflow and mlflow/mlflow-db exists; delete it and rerun so both hold one password.")
    for ns in ("mlflow", "ai-team"):
        ensure_namespace(ns)
    if not have_role:
        pw = secrets.token_urlsafe(24)
        create(secret("lab-pg-mlflow", {"username": "mlflow", "password": pw}, "kubernetes.io/basic-auth",
                      {"cnpg.io/reload": "true"}))
        create(secret("mlflow-db", {"uri": f"postgresql://mlflow:{pw}@lab-pg-rw.lab-data.svc:5432/mlflow"},
                      namespace="mlflow"))
    added = False
    for ident, (ns, sec, actions) in IDENTITIES.items():
        if ident in names:
            if not exists("secret", sec, ns):
                sys.exit(f"S3 identity {ident} exists but {ns}/{sec} does not; remove the identity and rerun")
            continue
        access, key = "lab" + ident + secrets.token_hex(6), secrets.token_urlsafe(30)
        cfg["identities"].append({"name": ident, "credentials": [{"accessKey": access, "secretKey": key}],
                                  "actions": actions})
        create(secret(sec, {"AWS_ACCESS_KEY_ID": access, "AWS_SECRET_ACCESS_KEY": key}, namespace=ns))
        added = True
    if added:
        s3c = secret("seaweedfs-s3-config", {"seaweedfs_s3_config": json.dumps(cfg)})
        r = kubectl("replace", "-f", "-", stdin=json.dumps(s3c))  # the whole Secret, from stdin, never a file
        if r.returncode:
            sys.exit(f"seaweedfs-s3-config: {r.stderr.strip()}")
        print("seaweedfs-s3-config: identities added; restart SeaweedFS to load them")


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
        training_platform(True)
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
    training_platform(False)


if __name__ == "__main__":
    main()
