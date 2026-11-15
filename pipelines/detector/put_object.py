#!/usr/bin/env python3
"""Put one file into the lab's bucket from the laptop, and read it back to check its sha256.

    KUBECONFIG=$PWD/.scratch_kube/config ~/.local/bin/uv run --no-project -q --python 3.12 --with boto3 \
      python -I pipelines/detector/put_object.py data/weights/base/yolo26n.pt models/base/yolo26n.pt

Spec: docs/specs/training-platform.md#decisions (row 7: the base weights copied once into the bucket). Goes through a
port-forward to SeaweedFS, signed with the key of the Secret lab-s3, held in memory only and never printed, as the
dataset upload of 2a does (pipelines/dataset/split_upload.py).
"""

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(ROOT / ".toolchain" / "bin" / "kubectl")
PORT, BUCKET = 18333, "lab-lake"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, key = Path(sys.argv[1]), sys.argv[2]
    import boto3
    data = json.loads(subprocess.run([KUBECTL, "get", "secret", "lab-s3", "-n", "lab-data", "-o", "json"],
                                     capture_output=True, text=True, check=True).stdout)["data"]
    access, secret = (base64.b64decode(data[k]).decode() for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"))
    pf = subprocess.Popen([KUBECTL, "port-forward", "-n", "lab-data", "svc/seaweedfs-all-in-one", f"{PORT}:8333"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = pf.stdout.readline()
        if not line.startswith("Forwarding from"):
            sys.exit(f"port-forward did not open: {line.strip()}")
        s3 = boto3.client("s3", endpoint_url=f"http://127.0.0.1:{PORT}", region_name="us-east-1",
                          aws_access_key_id=access, aws_secret_access_key=secret)
        body = src.read_bytes()
        s3.put_object(Bucket=BUCKET, Key=key, Body=body)
        back = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        a, b = hashlib.sha256(body).hexdigest(), hashlib.sha256(back).hexdigest()
        print(f"s3://{BUCKET}/{key}: {len(back):,} bytes, sha256 {b}" + ("" if a == b else f" DIFFERS from {a}"))
        if a != b:
            sys.exit(1)
    finally:
        pf.terminate()


if __name__ == "__main__":
    main()
