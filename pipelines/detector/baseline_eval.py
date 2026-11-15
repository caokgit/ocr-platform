#!/usr/bin/env python3
"""Score a detector's weights on three page sets of a dataset copy, by what the production weights saw in training.

    export YOLO_CONFIG_DIR=$PWD/.scratch_ultralytics YOLO_OFFLINE=1
    ~/.local/bin/uv run --no-project -q --python 3.12 --with ultralytics==8.4.142 --with torch --with torchvision \
      --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
      python -I pipelines/detector/baseline_eval.py <copy folder> <weights.pt> <out dir outside the repo>

Spec: docs/specs/ml-platform.md#t1s-baseline-measured-ahead-of-2b. Sets: A the test split (cut by split_upload.split,
its sha256 checked), B the copy's validation split, C the documents whose every page is in that validation split.
Prints one JSON line per set.
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipelines" / "dataset"))
sys.path.insert(0, str(ROOT / "pipelines" / "detector"))
from split_upload import split  # noqa: E402  the test split's one definition

from gate import TEST_SHA256  # noqa: E402  the frozen split's sha256, one definition


def page_sets(copy):
    manifest = json.loads((copy / "manifest.json").read_text())
    by_doc = defaultdict(list)
    for img in manifest["images"]:
        by_doc[re.match(r"(.+)_p\d+\.jpg$", img["file"]).group(1)].append(img)
    text, summary = split(copy)
    if summary["test_txt_sha256"] != TEST_SHA256:
        sys.exit(f"test split sha256 {summary['test_txt_sha256']} is not the frozen {TEST_SHA256}")
    test = text.split()
    val = [f"images/val/{i['file']}" for i in manifest["images"] if i["split"] == "val"]
    clean = [f"images/val/{i['file']}" for imgs in by_doc.values() if all(i["split"] == "val" for i in imgs)
             for i in imgs]
    return {"A_test_split": test, "B_validation_split": val, "C_unseen_documents": clean}


def main(copy, weights, out):
    copy, out = Path(copy).resolve(), Path(out).resolve()
    if out.is_relative_to(ROOT):
        sys.exit(f"{out} is inside the repo")
    out.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS
    SETTINGS.update(sync=False)
    for name, pages in page_sets(copy).items():
        listing = out / f"{name}.txt"
        listing.write_text("".join(f"{copy / p}\n" for p in sorted(pages)))
        data = out / f"{name}.yaml"
        data.write_text(f"train: {listing}\nval: {listing}\nnames:\n  0: item\n")
        boxes = sum(len([line for line in (copy / p.replace("images/", "labels/", 1)).with_suffix(".txt")
                         .read_text().splitlines() if line.strip()]) for p in pages)
        start = time.time()
        m = YOLO(weights).val(data=str(data), imgsz=640, batch=8, single_cls=True, device="cpu", plots=False,
                              project=str(out), name=name, exist_ok=True, verbose=False)
        print(json.dumps({"set": name, "pages": len(pages), "boxes": boxes,
                          "precision": round(float(m.box.mp), 4), "recall": round(float(m.box.mr), 4),
                          "mAP50": round(float(m.box.map50), 4), "mAP50_95": round(float(m.box.map), 4),
                          "seconds": round(time.time() - start, 1)}), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
