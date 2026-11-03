#!/usr/bin/env python3
"""Fetch an Ultralytics Platform NDJSON snapshot into a local YOLO copy, keeping original file names.

    python3 -I pipelines/dataset/fetch_ultralytics_ndjson.py <snapshot.ndjson>            # fetch, then verify
    python3 -I pipelines/dataset/fetch_ultralytics_ndjson.py <snapshot.ndjson> --verify   # local checks only

Spec: docs/specs/dataset-intake.md#ultralytics-snapshot-to-a-local-yolo-copy
Image URLs are signed: they are never printed, logged or stored.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jpeg_size(path):
    """(width, height) from the JPEG's frame header, or None when the file is not a readable JPEG."""
    with open(path, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            return None
        while True:
            byte = f.read(1)
            while byte and byte != b"\xff":
                byte = f.read(1)
            while byte == b"\xff":
                byte = f.read(1)
            if not byte:
                return None
            marker = byte[0]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(f.read(2), "big")
            if marker in SOF_MARKERS:
                segment = f.read(5)
                return int.from_bytes(segment[3:5], "big"), int.from_bytes(segment[1:3], "big")
            f.seek(length - 2, os.SEEK_CUR)


def load(ndjson):
    lines = [json.loads(line) for line in ndjson.read_text().splitlines() if line.strip()]
    dataset, images = lines[0], lines[1:]
    if dataset.get("type") != "dataset" or dataset.get("task") != "detect":
        sys.exit("expected a detect dataset line first")
    return dataset, images


def snapshot_dir(ndjson, dataset, out_root):
    snapshot_id = f"{dataset['updated_at'][:10]}-{sha256(ndjson)[:12]}"
    return out_root / dataset["name"] / snapshot_id


def image_ok(path, rec):
    return path.is_file() and jpeg_size(path) == (rec["width"], rec["height"])


def fetch_one(rec, path, retries=4):
    """Download one image to `path`; returns None on success, else a reason that holds no URL."""
    tmp = path.with_suffix(path.suffix + ".part")
    reason = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(rec["url"], headers={"User-Agent": "ml-lab-fetch/1"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                while chunk := resp.read(1 << 16):
                    f.write(chunk)
            if image_ok(tmp, rec):
                tmp.replace(path)
                return None
            reason = "not a JPEG of the expected size"
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
            if e.code in (401, 403, 404):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = type(e).__name__
        time.sleep(2 ** attempt)
    tmp.unlink(missing_ok=True)
    return reason


def write_labels_and_yaml(dest, dataset, images):
    """Labels for the images on disk; a missing image gets no label, so the copy stays consistent."""
    for rec in images:
        label = dest / "labels" / rec["split"] / (Path(rec["file"]).stem + ".txt")
        label.parent.mkdir(parents=True, exist_ok=True)
        boxes = rec.get("annotations", {}).get("boxes", [])
        label.write_text("".join(" ".join(str(v) for v in box) + "\n" for box in boxes))
    splits = sorted({rec["split"] for rec in images})
    names = "".join(f"  {int(k)}: {json.dumps(v)}\n" for k, v in sorted(dataset["class_names"].items()))
    # No `path:` key, so Ultralytics resolves the split folders against this file's own folder.
    (dest / "data.yaml").write_text("".join(f"{s}: images/{s}\n" for s in splits) + "names:\n" + names)


def write_manifest(dest, ndjson, dataset, images, missing):
    manifest = {
        "ndjson_sha256": sha256(ndjson),
        "dataset": {k: dataset.get(k) for k in ("name", "task", "version", "created_at", "updated_at", "bytes",
                                                 "class_names")},
        "images": [
            {"split": r["split"], "file": r["file"], "bytes": (p := dest / "images" / r["split"] / r["file"]).stat().st_size,
             "sha256": sha256(p), "width": r["width"], "height": r["height"],
             "boxes": len(r.get("annotations", {}).get("boxes", []))}
            for r in images
        ],
        # Images the source no longer serves (HTTP 404): recorded, not silently dropped.
        "missing": missing,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")


def previous_missing(dest):
    path = dest / "manifest.json"
    return json.loads(path.read_text()).get("missing", {}) if path.is_file() else {}


def verify(dest, images):
    problems = []
    manifest = json.loads((dest / "manifest.json").read_text())
    missing = manifest.get("missing", {})
    images = [r for r in images if r["file"] not in missing]
    by_file = {m["file"]: m for m in manifest["images"]}
    counts, lines, empty = Counter(), 0, 0
    for rec in images:
        path = dest / "images" / rec["split"] / rec["file"]
        if not image_ok(path, rec):
            problems.append(f"{rec['file']}: missing or wrong size")
            continue
        counts[rec["split"]] += 1
        if by_file.get(rec["file"], {}).get("sha256") != sha256(path):
            problems.append(f"{rec['file']}: sha256 differs from the manifest")
        label = (dest / "labels" / rec["split"] / (Path(rec["file"]).stem + ".txt")).read_text().splitlines()
        if len(label) != len(rec.get("annotations", {}).get("boxes", [])):
            problems.append(f"{rec['file']}: label lines differ from the NDJSON boxes")
        lines += len(label)
        empty += not label
    expected = Counter(r["split"] for r in images)
    print(f"images per split: {dict(counts)} (expected: NDJSON minus recorded missing {dict(expected)})")
    print(f"label lines: {lines}, empty label files: {empty}")
    print(f"total bytes: {sum(m['bytes'] for m in manifest['images'])}")
    for name, reason in missing.items():
        print(f"WARNING: {name} missing at the source ({reason}), recorded in manifest.json")
    for p in problems[:20]:
        print("problem:", p)
    print(f"{len(problems)} problem(s)")
    return not problems and counts == expected


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ndjson", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/ultralytics"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--verify", action="store_true", help="only check the local copy")
    args = ap.parse_args()

    dataset, images = load(args.ndjson)
    dest = snapshot_dir(args.ndjson, dataset, args.out)
    print(f"snapshot: {dest}")
    if not args.verify:
        for split in {r["split"] for r in images}:
            (dest / "images" / split).mkdir(parents=True, exist_ok=True)
        known_missing = previous_missing(dest)
        todo = [r for r in images
                if r["file"] not in known_missing and not image_ok(dest / "images" / r["split"] / r["file"], r)]
        print(f"images: {len(images)}, already present: {len(images) - len(todo) - len(known_missing)}, "
              f"recorded missing: {len(known_missing)}, to fetch: {len(todo)}")
        failed, start = {}, time.time()
        with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
            jobs = {pool.submit(fetch_one, r, dest / "images" / r["split"] / r["file"]): r for r in todo}
            for n, job in enumerate(concurrent.futures.as_completed(jobs), 1):
                if (reason := job.result()) is not None:
                    failed[jobs[job]["file"]] = reason
                if n % 250 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)} done, {len(failed)} failed, {time.time() - start:.0f} s")
        if failed:
            print(f"{len(failed)} image(s) not fetched: {dict(Counter(failed.values()))}")
            for name in sorted(failed)[:20]:
                print("  ", name, failed[name])
        if any(reason != "HTTP 404" for reason in failed.values()):
            return 1  # transient failures: rerun to fetch the rest
        missing = {**{r["file"]: "HTTP 404" for r in images if r["file"] in failed}, **previous_missing(dest)}
        present = [r for r in images if r["file"] not in missing]
        write_labels_and_yaml(dest, dataset, present)
        write_manifest(dest, args.ndjson, dataset, present, missing)
    return 0 if verify(dest, images) else 1


if __name__ == "__main__":
    sys.exit(main())
