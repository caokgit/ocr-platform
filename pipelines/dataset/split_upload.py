#!/usr/bin/env python3
"""Cut the detector test split from a dataset copy and put the copy and the split in the lab's bucket.

    KUBECONFIG=$PWD/.scratch_kube/config python3 -I pipelines/dataset/split_upload.py <copy folder>
    python3 -I pipelines/dataset/split_upload.py <copy folder> --dry-run     # the split only, nothing uploaded

Spec: docs/specs/data-path.md#gold-sets (the test split), acceptance B11; row 4 (the laptop copies, the box holds no
Azure identity). A page's garment spec is its file name before `_p<page>`; the garment specs are sorted, shuffled with SEED,
and the first 26 are test; every page of a test garment spec is test. Uploads go to s3://lab-lake through a
port-forward to SeaweedFS, signed with the key of the Secret lab-s3, held in memory only and never printed.
"""

import argparse
import base64
import datetime
import hashlib
import hmac
import http.client
import json
import random
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(ROOT / ".toolchain" / "bin" / "kubectl")
SEED = 20261101          # the split's seed: changing it makes a different split (and a different list sha256)
TEST_GARMENT_SPECS = 26      # 20% of 132, rounded down (spec row 20)
BUCKET, REGION, PORT = "lab-lake", "us-east-1", 18333


def split(copy):
    manifest = json.loads((copy / "manifest.json").read_text())
    pages = {}
    for img in manifest["images"]:
        m = re.match(r"(.+)_p\d+\.jpg$", img["file"])
        pages.setdefault(m.group(1), []).append(f"images/{img['split']}/{img['file']}")
    garment_specs = sorted(pages)
    order = garment_specs[:]
    random.Random(SEED).shuffle(order)
    test = sorted(order[:TEST_GARMENT_SPECS])
    test_pages = sorted(p for t in test for p in pages[t])
    text = "\n".join(test_pages) + "\n"
    rest = set(garment_specs) - set(test)
    assert not rest & set(test)
    summary = {"copy_id": copy.name, "seed": SEED, "garment_specs": len(garment_specs), "test_garment_specs": len(test),
               "test_pages": len(test_pages), "rest_pages": sum(len(pages[t]) for t in rest),
               "test_txt_sha256": hashlib.sha256(text.encode()).hexdigest(), "test_garment_spec_names": test}
    return text, summary


def s3_key():
    def get(k):
        return base64.b64decode(subprocess.run(
            [KUBECTL, "get", "secret", "lab-s3", "-n", "lab-data", "-o", f"jsonpath={{.data.{k}}}"],
            capture_output=True, text=True, check=True).stdout).decode()
    return get("AWS_ACCESS_KEY_ID"), get("AWS_SECRET_ACCESS_KEY")


class S3:
    """PUT and HEAD on one keep-alive connection, signed with AWS Signature Version 4 (path-style)."""

    def __init__(self, access, secret):
        self.access, self.secret = access, secret
        self.conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)

    def _sign(self, method, path, payload_hash):
        now = datetime.datetime.now(datetime.timezone.utc)
        amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        host = f"127.0.0.1:{PORT}"
        canonical = "\n".join([method, path, "", f"host:{host}", f"x-amz-content-sha256:{payload_hash}",
                               f"x-amz-date:{amz}", "", "host;x-amz-content-sha256;x-amz-date", payload_hash])
        scope = f"{day}/{REGION}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = ("AWS4" + self.secret).encode()
        for part in (day, REGION, "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        return {"Host": host, "x-amz-date": amz, "x-amz-content-sha256": payload_hash,
                "Authorization": f"AWS4-HMAC-SHA256 Credential={self.access}/{scope}, "
                                 f"SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature={sig}"}

    def _call(self, method, key, body=b""):
        path = "/" + BUCKET + "/" + urllib.parse.quote(key)
        h = self._sign(method, path, hashlib.sha256(body).hexdigest())
        self.conn.request(method, path, body=body or None, headers=h)
        r = self.conn.getresponse()
        data = r.read()
        return r.status, r.getheader("Content-Length"), data

    def size(self, key):
        status, length, _ = self._call("HEAD", key)
        return int(length) if status == 200 else None

    def put(self, key, body):
        status, _, data = self._call("PUT", key, body)
        if status != 200:
            raise RuntimeError(f"PUT {key}: HTTP {status} {data[:200]!r}")


def upload(copy, text, summary):
    pf = subprocess.Popen([KUBECTL, "port-forward", "-n", "lab-data", "svc/seaweedfs-all-in-one", f"{PORT}:8333"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = pf.stdout.readline()
        if not line.startswith("Forwarding from"):
            sys.exit(f"port-forward did not open: {line.strip()}")
        s3 = S3(*s3_key())
        files = sorted(p for p in copy.rglob("*") if p.is_file())
        sent = skipped = 0
        for n, p in enumerate(files, 1):
            key = f"datasets/ultralytics/{copy.name}/{p.relative_to(copy)}"
            body = p.read_bytes()
            if s3.size(key) == len(body):
                skipped += 1
            else:
                s3.put(key, body)
                sent += len(body)
            if n % 500 == 0:
                print(f"{n}/{len(files)} files ({sent:,} bytes sent, {skipped} already there)", flush=True)
        prefix = f"splits/{copy.name}/"
        s3.put(prefix + "test.txt", text.encode())
        s3.put(prefix + "split.json", (json.dumps(summary, indent=2) + "\n").encode())
        print(f"uploaded: {len(files)} dataset files ({sent:,} bytes sent, {skipped} already there); "
              f"s3://{BUCKET}/{prefix}test.txt and split.json")
    finally:
        pf.terminate()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("copy", help="the dataset copy folder (data/ultralytics/<name>/<copy id>)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print the split, upload nothing")
    args = ap.parse_args()
    copy = Path(args.copy).resolve()
    text, summary = split(copy)
    print(f"B11 split of {copy.name}: {summary['test_garment_specs']} of {summary['garment_specs']} garment specs "
          f"({summary['test_pages']} pages) test, {summary['rest_pages']} pages train and validation, no garment spec in "
          f"both; seed {SEED}; test.txt sha256 {summary['test_txt_sha256']}")
    if not args.dry_run:
        upload(copy, text, summary)


if __name__ == "__main__":
    main()
