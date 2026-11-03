"""Drop the lake's streamed tables, files included, for a full new fill (docs/specs/data-path.md#replay): bronze and
silver by default, or only the namespaces given as arguments. Gold is never dropped by a reset."""

import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402

targets = sys.argv[1:] or ["bronze", "silver"]
if "gold" in targets:
    raise SystemExit("a reset never drops gold")
spark = session("lab-reset")
for ns in targets:
    if not spark.sql(f"SHOW NAMESPACES IN {CATALOG}").where(f"namespace = '{ns}'").count():
        continue
    tables = [r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.{ns}").collect()]
    for t in tables:
        spark.sql(f"DROP TABLE {CATALOG}.{ns}.{t} PURGE")
    print(f"reset: {ns}, {len(tables)} tables dropped with their files", flush=True)
spark.stop()
