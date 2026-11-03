"""Acceptance numbers read from the lake (docs/specs/data-path.md#acceptance): silver rows per table and environment
(B4, compared with the copy's manifest), silver.pdf (B5), Debezium's lag per event from bronze (B4: the time
Debezium produced it minus its commit in live), bronze duplicates by Kafka partition and offset (B9), and the largest event that crossed (B14)."""

import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402

spark = session("lab-checks")
silver = sorted(r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.silver").collect())
print("silver rows (table env rows):")
for t in silver:
    if t == "pdf":
        continue
    for r in spark.sql(f"SELECT env, count(*) n FROM {CATALOG}.silver.{t} GROUP BY env ORDER BY env").collect():
        print(f"  {t} {r.env} {r.n}")
truth = spark.sql(f"SELECT count(DISTINCT content_hash) FROM {CATALOG}.silver.document "
                  "WHERE content_hash IS NOT NULL AND content_hash != '' AND NOT _is_deleted").first()[0]
print(f"B5 silver.pdf rows: {spark.table(f'{CATALOG}.silver.pdf').count()} "
      f"(distinct content_hash in silver.document: {truth})")

bronze = [r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.bronze").collect()]
union = " UNION ALL ".join(
    f"SELECT '{t}' t, kafka_partition, kafka_offset, op, "
    f"unix_millis(kafka_timestamp) - source_ts_ms AS lag_ms FROM {CATALOG}.bronze.{t}" for t in bronze)
spark.sql(union).createOrReplaceTempView("events")
lag = spark.sql("""SELECT count(*) n, round(percentile(lag_ms, 0.5) / 1000, 2) p50_s,
    round(percentile(lag_ms, 0.99) / 1000, 2) p99_s, round(max(lag_ms) / 1000, 2) max_s,
    sum(CASE WHEN lag_ms > 10000 THEN 1 ELSE 0 END) over_10s FROM events WHERE op != 'r'""").first()
print(f"B4 Debezium lag over {lag.n} change events: p50 {lag.p50_s} s, p99 {lag.p99_s} s, max {lag.max_s} s, "
      f"{lag.over_10s} events over 10 s")
dup = spark.sql("SELECT count(*) - count(DISTINCT t, kafka_partition, kafka_offset) d FROM events").first().d
print(f"B9 bronze duplicates (same topic, partition, offset): {dup}")
big = spark.sql(" UNION ALL ".join(f"SELECT '{t}' t, max(octet_length(value)) b FROM {CATALOG}.bronze.{t}"
                                   for t in bronze)).orderBy("b", ascending=False).limit(3).collect()
print("B14 largest events in bronze: " + ", ".join(f"{r.t} {r.b:,} bytes" for r in big))
spark.stop()
