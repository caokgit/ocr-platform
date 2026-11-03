"""Acceptance B3: a Spark 4.1.4 job under the operator writes one Iceberg table through the JDBC catalog and reads
it back (docs/specs/data-path.md#acceptance)."""

import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402

spark = session("lab-smoke")
t = f"{CATALOG}.smoke.b3"
spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.smoke")
spark.sql(f"CREATE TABLE IF NOT EXISTS {t} (id BIGINT, note STRING) USING iceberg")
spark.sql(f"INSERT INTO {t} VALUES (1, 'spark {spark.version} wrote this')")
rows = spark.sql(f"SELECT count(*) FROM {t}").first()[0]
snap = spark.sql(f"SELECT snapshot_id, committed_at FROM {t}.snapshots ORDER BY committed_at DESC LIMIT 1").first()
loc = spark.sql(f"SELECT file_path FROM {t}.files LIMIT 1").first()[0]
print(f"B3: Spark {spark.version}, {t} holds {rows} rows, latest snapshot {snap[0]} at {snap[1]}, a data file {loc}")
spark.stop()
