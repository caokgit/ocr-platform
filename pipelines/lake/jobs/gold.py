"""The human gold set: each person-chosen crop of the curated results joined to the service unit it was cut from
(the V6 rule), as gold.human_picks; the crops that do not join, with the reason, as gold.human_picks_excluded
(docs/specs/data-path.md#gold-sets, acceptance B10).

    arguments: <copy id>     e.g. 2026-11-01-ffcc03c52aea (recorded with the build)

The rule, per filled slot of a result page: its crop source names a page image (/web/content/<attachment id>,
sometimes with ?unique=...) whose attachment is ocr-page-<run>-p<page>[-annot|-clean].png; the crop's box, relative
to the page image, is compared with every unit of that run and page in either service copy, each unit's box taken
for the same render (bbox_annot, bbox_clean or bbox), relative to its render; the best unit at IoU 0.9 or more
joins. Silver is read at fixed snapshots, recorded in the build's commit with the copy id; the build is tagged.
"""

import datetime
import hashlib
import json
import re
import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

IOU_MIN = 0.9
copy_id = sys.argv[1]
spark = session("lab-gold")
spark.conf.set("spark.sql.session.timeZone", "UTC")
READ = ["request_ticket_result", "ir_attachment", "document_unit", "ocr_element", "match_candidate"]
snap = {t: spark.sql(f"SELECT snapshot_id FROM {CATALOG}.silver.{t}.snapshots ORDER BY committed_at DESC LIMIT 1")
        .first()[0] for t in READ}


def silver(t, cols):
    return spark.read.option("versionAsOf", snap[t]).table(f"{CATALOG}.silver.{t}").where("NOT _is_deleted") \
        .select(*cols).collect()


results = silver("request_ticket_result", ["env", "id", "result", "saved_by_domain"])
names = {(r.env, r.id): r.name for r in silver("ir_attachment", ["env", "id", "name"])}
codes = {(r.env, str(r.id)): r.code for r in silver("ocr_element", ["env", "id", "code"])}
units = {}
for u in silver("document_unit", ["env", "run_id", "page_index", "unit_id", "kind", "bbox", "bbox_annot",
                                  "bbox_clean", "pdf_to_image", "render_width", "render_height"]):
    units.setdefault((u.run_id, u.page_index), []).append(u)
first = {}
for c in silver("match_candidate", ["env", "run_id", "element_code", "unit_id", "rank", "rerank_score"]):
    if c.rank == 1:
        first[(c.run_id, c.element_code)] = (c.unit_id, c.rerank_score)


def rel_unit(u, render):
    raw = {"annot": u.bbox_annot, "clean": u.bbox_clean}.get(render) or u.bbox
    b, z = json.loads(raw), json.loads(u.pdf_to_image)[0]
    return (b["x0"] * z / u.render_width, b["y0"] * z / u.render_height,
            b["x1"] * z / u.render_width, b["y1"] * z / u.render_height)


def iou(a, b):
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union > 0 else 0.0


picks, excluded = [], []
for r in results:
    for p in (json.loads(r.result) if r.result else {}).get("pages", []):
        slots = (p.get("customPageDef") or {}).get("elements") or []
        for i, crop in enumerate(p.get("imageCropSources") or []):
            if not crop or not crop.get("bbox") or not crop.get("pageImageUrl"):
                continue                                   # an empty slot: no crop, no label
            slot = slots[i] if i < len(slots) else {}
            ids = slot.get("ocrClassifications") or []
            code = codes.get((r.env, ids[0])) if ids else None
            base = dict(env=r.env, result_id=r.id, page_number=p.get("pageNumber"), slot_index=i,
                        slot_id=slot.get("id"), element_id=ids[0] if ids else None, element_code=code)
            m = re.search(r"/web/content/(\d+)", crop["pageImageUrl"])
            name = names.get((r.env, int(m.group(1)))) if m else None
            page_image = re.match(r"ocr-page-([0-9a-f]+)-p(\d+)(?:-(annot|clean))?", name or "")
            if not page_image:
                excluded.append({**base, "reason": "page image gone" if not name else "not a page image",
                                 "page_image_attachment_id": int(m.group(1)) if m else None})
                continue
            run, page, render = page_image.group(1), int(page_image.group(2)), page_image.group(3) or "plain"
            bb = crop["bbox"]
            c = (bb["x_min"] / crop["pageWidth"], bb["y_min"] / crop["pageHeight"],
                 bb["x_max"] / crop["pageWidth"], bb["y_max"] / crop["pageHeight"])
            cands = units.get((run, page), [])
            if not cands:
                excluded.append({**base, "reason": "run or page not in either service copy",
                                 "page_image_attachment_id": int(m.group(1))})
                continue
            score, best = max(((iou(c, rel_unit(u, render)), u) for u in cands), key=lambda t: t[0])
            if score < IOU_MIN:
                excluded.append({**base, "reason": f"no unit at IoU {IOU_MIN} (best {score:.3f})",
                                 "page_image_attachment_id": int(m.group(1))})
                continue
            top = first.get((run, code))
            picks.append({**base, "run_id": run, "page_index": page, "render": render, "unit_env": best.env,
                          "unit_id": best.unit_id, "unit_kind": best.kind, "iou": round(score, 4),
                          "saved_by_domain": r.saved_by_domain,
                          "service_first_unit_id": top[0] if top else None,
                          "service_first_rerank_score": top[1] if top else None,
                          "picked_service_first": bool(top and top[0] == best.unit_id)})

S, I, L, D, B = T.StringType(), T.IntegerType(), T.LongType(), T.DoubleType(), T.BooleanType()
common = [("env", S), ("result_id", I), ("page_number", I), ("slot_index", I), ("slot_id", S),
          ("element_id", S), ("element_code", S)]
pick_schema = T.StructType([T.StructField(n, t) for n, t in common + [
    ("run_id", S), ("page_index", I), ("render", S), ("unit_env", S), ("unit_id", S), ("unit_kind", S),
    ("iou", D), ("saved_by_domain", S), ("service_first_unit_id", S), ("service_first_rerank_score", D),
    ("picked_service_first", B)]])
excl_schema = T.StructType([T.StructField(n, t) for n, t in common + [("reason", S), ("page_image_attachment_id", L)]])

def read_hash(table, sid):
    """sha256 of the table's rows at one snapshot, read by its id, in a fixed order (B10)."""
    rows = spark.sql(f"SELECT * FROM {CATALOG}.gold.{table} VERSION AS OF {sid}").collect()
    lines = sorted(json.dumps(r.asDict(), sort_keys=True, default=str) for r in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.gold")
build = datetime.datetime.now(datetime.timezone.utc)
props = {"snapshot-property.lab.copy-id": copy_id, "snapshot-property.lab.silver-snapshots": json.dumps(snap),
         "snapshot-property.lab.build": build.isoformat(timespec="seconds")}
tag = f"build_{build:%Y%m%d_%H%M%S}"
for table, rows, schema in (("human_picks", picks, pick_schema), ("human_picks_excluded", excluded, excl_schema)):
    df = spark.createDataFrame([tuple(r.get(f.name) for f in schema.fields) for r in rows], schema)
    w = df.orderBy("env", "result_id", "page_number", "slot_index").writeTo(f"{CATALOG}.gold.{table}")
    for k, v in props.items():
        w = w.option(k, v)
    w.createOrReplace()
    sid = spark.sql(f"SELECT snapshot_id FROM {CATALOG}.gold.{table}.snapshots ORDER BY committed_at DESC LIMIT 1").first()[0]
    spark.sql(f"ALTER TABLE {CATALOG}.gold.{table} CREATE TAG {tag} AS OF VERSION {sid}")
    a, b = (read_hash(table, sid) for _ in range(2))
    print(f"gold.{table}: {len(rows)} rows, snapshot {sid}, tag {tag}; read twice by snapshot id: "
          f"{'the same rows' if a == b else 'DIFFERENT'}", flush=True)

by_reason = {}
for e in excluded:
    by_reason[e["reason"]] = by_reason.get(e["reason"], 0) + 1
per_env = {env: sum(1 for p in picks if p["env"] == env) for env in ("dev", "stg")}
print(f"B10: {len(picks)} picks {per_env}, {len(excluded)} excluded {by_reason}; "
      f"the person kept the service's first pick in {sum(p['picked_service_first'] for p in picks)} of {len(picks)}; "
      f"copy {copy_id}, silver snapshots {snap}", flush=True)
spark.stop()
