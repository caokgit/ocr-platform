"""What the training platform's pods share: the bucket, sha256, the dataset copy and its splits.

Spec: docs/specs/training-platform.md#decisions (rows 7, 8). Runs in the Ultralytics image, with boto3 from
requirements.txt; settings come from the environment the WorkflowTemplate sets.
"""

import hashlib
import json
import os
import random
import re
from pathlib import Path

BUCKET = os.environ.get("LAB_BUCKET", "lab-lake")
DOC = re.compile(r"(.+)_p\d+\.jpg$")
VAL_SEED = 0          # the validation cut by document (row 8)
VAL_SHARE = 0.10      # of the documents left after the test split, rounded up


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def s3():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1")


def fetch(client, key, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(BUCKET, key, str(dest))
    return dest


def fetch_prefix(client, prefix, dest, keep=None):
    """Download every object under prefix (only the relative paths keep accepts, if given); return the count."""
    n = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):]
            if keep is None or keep(rel):
                fetch(client, obj["Key"], Path(dest) / rel)
                n += 1
    return n


def test_list(client, dataset, dest):
    """The frozen test split's list from splits/<dataset>/test.txt (its sha256 is checked by gate.test_pages)."""
    return fetch(client, f"splits/{dataset}/test.txt", Path(dest) / "test.txt")


def fetch_copy(client, dataset, dest, only=None):
    """The dataset copy (or only the listed images and their labels), each image checked against the manifest."""
    dest = Path(dest)
    prefix = f"datasets/ultralytics/{dataset}/"
    fetch(client, prefix + "manifest.json", dest / "manifest.json")
    manifest = json.loads((dest / "manifest.json").read_text())
    wanted = None
    if only is not None:
        wanted = set(only) | {p.replace("images/", "labels/", 1).rsplit(".", 1)[0] + ".txt" for p in only}
    n = fetch_prefix(client, prefix, dest, keep=lambda rel: rel.startswith(("images/", "labels/")) and
                     (wanted is None or rel in wanted))
    bad = [i["file"] for i in manifest["images"]
           if (p := dest / "images" / i["split"] / i["file"]).exists() and sha256(p) != i["sha256"]]
    if bad:
        raise SystemExit(f"{len(bad)} images differ from the manifest, first {bad[0]}")
    return manifest, n


def split_as_copy(manifest):
    """Diagnostic only (spec, row 16): the copy's own train and validation pages, as production trained."""
    train = sorted(f"images/train/{i['file']}" for i in manifest["images"] if i["split"] == "train")
    val = sorted(f"images/val/{i['file']}" for i in manifest["images"] if i["split"] == "val")
    return train, val, sorted({DOC.match(Path(p).name).group(1) for p in val})


def split_for_training(manifest, test_pages):
    """Pages left after the test documents, cut into train and validation by whole document (row 8)."""
    test_docs = {DOC.match(Path(p).name).group(1) for p in test_pages}
    by_doc = {}
    for i in manifest["images"]:
        by_doc.setdefault(DOC.match(i["file"]).group(1), []).append(f"images/{i['split']}/{i['file']}")
    rest = sorted(d for d in by_doc if d not in test_docs)
    k = -(-len(rest) * int(VAL_SHARE * 100) // 100)  # rounded up
    val_docs = sorted(random.Random(VAL_SEED).sample(rest, k))
    train = sorted(p for d in rest if d not in val_docs for p in by_doc[d])
    val = sorted(p for d in val_docs for p in by_doc[d])
    return train, val, val_docs
