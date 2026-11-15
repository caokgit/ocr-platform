#!/usr/bin/env python3
"""The detector's gate: score @champion and a candidate on the frozen test split, bootstrap over its documents.

    export YOLO_CONFIG_DIR=$PWD/.scratch_ultralytics YOLO_OFFLINE=1
    ~/.local/bin/uv run --no-project -q --python 3.12 --with ultralytics==8.4.142 --with torch --with torchvision \
      --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
      python -I pipelines/detector/gate.py <copy folder> <out dir outside the repo> <champion.pt> [<candidate.pt>] \
      [--margins <m1>,<m2>]

Spec: docs/specs/training-platform.md#the-gate. With the champion alone it prints the champion's numbers and their
interval; with a candidate it prints the difference (candidate minus champion) with its interval, and, given the
margins, the rule's result. Writes report.json and report.txt into the out dir.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TEST_SHA256 = "dad44960e5cc607479f0c9b8caf0a0a646181a99df0b2b9491ac1908203edc1c"  # data-path spec, decision 20

SERVICE = {"conf": 0.65, "iou": 0.3}  # the OCR service's own setting (docs/lab/ocr-workload.md)
DEFAULTS = {"conf": None, "iou": 0.7}  # Ultralytics' val defaults (confidence 0.001), for mAP
RESAMPLES, SEED = 2000, 0
DOC = re.compile(r"(.+)_p\d+\.jpg$")


def test_pages(copy, listing=None):
    """The frozen test split: from its list file (the bucket's copy, in a pod) or cut again (on the laptop)."""
    if listing:
        text = Path(listing).read_text()
    else:
        sys.path.insert(0, str(ROOT / "pipelines" / "dataset"))
        from split_upload import split  # the test split's one definition
        text = split(copy)[0]
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != TEST_SHA256:
        sys.exit(f"test split sha256 {digest} is not the frozen {TEST_SHA256}")
    return sorted(text.split())


def score(weights, data, setting, out, name):
    """Run Ultralytics' validator once; keep each page's matching (tp at 10 IoUs, conf, classes) by image name."""
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect.val import DetectionValidator

    kept = {}

    class KeepPages(DetectionValidator):
        def update_metrics(self, preds, batch):
            update = self.metrics.update_stats

            def keep(stat):
                kept[stat["im_name"]] = {k: np.array(stat[k], copy=True) for k in ("tp", "conf", "target_cls")}
                update(stat)

            self.metrics.update_stats = keep
            try:
                super().update_metrics(preds, batch)
            finally:
                self.metrics.update_stats = update

    start = time.time()
    m = YOLO(weights).val(validator=KeepPages, data=str(data), imgsz=640, batch=8, single_cls=True, device="cpu",
                          plots=False, project=str(out), name=name, exist_ok=True, verbose=False, **setting)
    return kept, {"mAP50": float(m.box.map50), "mAP50_95": float(m.box.map)}, round(time.time() - start, 1)


def by_document(kept, pages):
    docs = defaultdict(list)
    for p in pages:
        docs[DOC.match(Path(p).name).group(1)].append(kept[Path(p).name])
    return {d: v for d, v in sorted(docs.items())}


def ap_on(docs_stats):
    """mAP@50 and mAP@50-95 on a list of documents (repeats allowed), by Ultralytics' own ap_per_class."""
    from ultralytics.utils.metrics import ap_per_class

    pages = [pg for doc in docs_stats for pg in doc]
    tp = np.concatenate([pg["tp"] for pg in pages])
    conf = np.concatenate([pg["conf"] for pg in pages])
    target = np.concatenate([pg["target_cls"] for pg in pages])
    ap = ap_per_class(tp, conf, np.zeros_like(conf), target)[5]
    return float(ap[:, 0].mean()), float(ap.mean())


def counts(doc):
    """Found boxes (IoU 0.5), human boxes, predicted boxes of one document at the service's setting."""
    return np.array([sum(int(pg["tp"][:, 0].sum()) for pg in doc), sum(len(pg["target_cls"]) for pg in doc),
                     sum(len(pg["conf"]) for pg in doc)])


def metrics(model, idx):
    """All four numbers of one model on documents idx (indices into the sorted document list)."""
    m50, m5095 = ap_on([model["map"][i] for i in idx])
    found, truth, predicted = model["op"][idx].sum(axis=0)
    return {"mAP50_95": m5095, "mAP50": m50, "recall_service": found / truth,
            "precision_service": found / max(predicted, 1)}


def evaluate(copy, out, weights, listing=None):
    pages = test_pages(copy, listing)
    listing = out / "test_split.txt"
    listing.write_text("".join(f"{copy / p}\n" for p in pages))
    data = out / "test_split.yaml"
    data.write_text(f"train: {listing}\nval: {listing}\nnames:\n  0: item\n")
    models = []
    for role, w in weights:
        kept_map, full_map, s1 = score(w, data, DEFAULTS, out, f"{role}_map")
        kept_op, _, s2 = score(w, data, SERVICE, out, f"{role}_service")
        map_docs, op_docs = by_document(kept_map, pages), by_document(kept_op, pages)
        models.append({"role": role, "weights": str(w), "ultralytics_val": full_map, "seconds": s1 + s2,
                       "docs": list(map_docs), "map": list(map_docs.values()),
                       "op": np.array([counts(d) for d in op_docs.values()])})
    return pages, models


def interval(values):
    lo, hi = np.percentile(values, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def run(copy, out, champion, candidate=None, margins=None, listing=None):
    """Score @champion (and a candidate) on the test split; return the report and its text table."""
    from ultralytics.utils import SETTINGS
    SETTINGS.update(sync=False)
    weights = [("champion", champion)] + ([("candidate", candidate)] if candidate else [])
    pages, models = evaluate(copy, out, weights, listing)
    n = len(models[0]["docs"])
    assert all(m["docs"] == models[0]["docs"] for m in models)
    full = [metrics(m, np.arange(n)) for m in models]
    rng = np.random.default_rng(SEED)
    draws = [rng.integers(0, n, n) for _ in range(RESAMPLES)]
    boot = [[metrics(m, idx) for idx in draws] for m in models]
    keys = list(full[0])

    report = {"test_split_sha256": TEST_SHA256, "documents": n, "pages": len(pages),
              "boxes": int(models[0]["op"][:, 1].sum()), "resamples": RESAMPLES, "seed": SEED,
              "setting_service": SERVICE, "models": []}
    for m, f, b in zip(models, full, boot):
        report["models"].append({"role": m["role"], "weights": m["weights"], "seconds": m["seconds"],
                                 "ultralytics_val": {k: round(v, 4) for k, v in m["ultralytics_val"].items()},
                                 **{k: {"value": round(f[k], 4), "interval": interval([x[k] for x in b])}
                                    for k in keys}})
    if candidate:
        diff = {k: {"value": round(full[1][k] - full[0][k], 4),
                    "interval": interval([c[k] - h[k] for h, c in zip(boot[0], boot[1])])} for k in keys}
        report["difference"] = diff
        if margins:
            m1, m2 = margins
            ok = diff["mAP50_95"]["interval"][0] >= -m1 and diff["recall_service"]["interval"][0] >= -m2
            report["rule"] = {"margins": {"mAP50_95": m1, "recall_service": m2}, "passed": ok,
                              "better": diff["mAP50_95"]["interval"][0] > 0}

    lines = [f"test split {TEST_SHA256[:8]}..., {n} documents, {len(pages)} pages, {report['boxes']} boxes; "
             f"interval: {RESAMPLES} resamples of the documents, seed {SEED}",
             f"{'':20}" + "".join(f"{m['role']:>26}" for m in report["models"])
             + (f"{'difference':>26}" if candidate else "")]
    for k in keys:
        cells = [f"{m[k]['value']:.3f} [{m[k]['interval'][0]:.3f}, {m[k]['interval'][1]:.3f}]"
                 for m in report["models"]]
        if candidate:
            d = report["difference"][k]
            cells.append(f"{d['value']:+.3f} [{d['interval'][0]:+.3f}, {d['interval'][1]:+.3f}]")
        lines.append(f"{k:20}" + "".join(f"{c:>26}" for c in cells))
    if "rule" in report:
        r = report["rule"]
        lines.append(f"rule: lower ends >= -{r['margins']['mAP50_95']} (mAP50_95), -{r['margins']['recall_service']}"
                     f" (recall_service): {'PASSED' if r['passed'] else 'FAILED'}"
                     + (", BETTER" if r["better"] else ""))
    (out / "report.json").write_text(json.dumps(report, indent=1))
    (out / "report.txt").write_text("\n".join(lines) + "\n")
    return report, lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("copy")
    ap.add_argument("out")
    ap.add_argument("champion")
    ap.add_argument("candidate", nargs="?")
    ap.add_argument("--margins", help="m1,m2: how far below @champion the lower ends of mAP@50-95 and recall may go")
    a = ap.parse_args()
    copy, out = Path(a.copy).resolve(), Path(a.out).resolve()
    if out.is_relative_to(ROOT):
        sys.exit(f"{out} is inside the repo")
    out.mkdir(parents=True, exist_ok=True)
    margins = tuple(float(x) for x in a.margins.split(",")) if a.margins else None
    report, lines = run(copy, out, a.champion, a.candidate, margins)
    print("\n".join(lines))
    print(json.dumps({m["role"]: {"ultralytics_val": m["ultralytics_val"], "seconds": m["seconds"]}
                      for m in report["models"]}))


if __name__ == "__main__":
    main()
