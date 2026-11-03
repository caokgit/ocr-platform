"""The streaming job: Kafka's 28 table topics into bronze (every event) and silver (each row's newest state), one
30-second micro-batch at a time (docs/specs/data-path.md#spark-and-the-catalog, rows 16 to 18).

Bronze: one table per topic; a batch's commit carries its batch id, and a table that already holds this batch id
is skipped, so a retried batch is never appended twice. Silver: one table per source table, both environments, key
env + id; the newest event per key in the batch (highest LSN) is merged, and only if its LSN is newer than the
row's. Columns come from the copy's schema.sql (in the ConfigMap); a column it does not know fails the batch.
"""

import re
import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import types as T  # noqa: E402
from pyspark.sql.window import Window  # noqa: E402
from pyspark.storagelevel import StorageLevel  # noqa: E402

BOOTSTRAP = "lab-kafka-kafka-bootstrap:9092"
CHECKPOINT = "/data/checkpoints/stream"
TRIGGER = "30 seconds"
MAX_EVENTS_PER_BATCH = 5000         # 20,000 got executors OOMKilled at 1.4 GiB (2026-11-01)

# Postgres type -> (how Debezium's JSON carries it, how to turn that into the silver column)
PARSE = {
    "character varying": (T.StringType(), None), "text": (T.StringType(), None), "jsonb": (T.StringType(), None),
    "tsvector": (T.StringType(), None), "integer": (T.IntegerType(), None), "smallint": (T.ShortType(), None),
    "bigint": (T.LongType(), None), "double precision": (T.DoubleType(), None), "boolean": (T.BooleanType(), None),
    "text[]": (T.ArrayType(T.StringType()), None),
    "timestamp without time zone": (T.LongType(), lambda c: F.timestamp_micros(c)),   # MicroTimestamp
    "timestamp with time zone": (T.StringType(), lambda c: F.to_timestamp(c)),        # ZonedTimestamp, ISO 8601
    "date": (T.IntegerType(), lambda c: F.date_add(F.lit("1970-01-01").cast("date"), c)),  # days since 1970
}


def read_schema(path="/opt/lab/schema.sql"):
    """{(schema, table): [(column, postgres type)]} from the copy's schema.sql."""
    out, cur = {}, None
    for line in open(path):
        m = re.match(r'CREATE TABLE (\w+)\."(\w+)" \(', line)
        if m:
            cur = out.setdefault((m.group(1), m.group(2)), [])
            continue
        m = re.match(r'\s+"(\w+)" (.+?)( NOT NULL)?,?$', line)
        if cur is not None and m:
            typ = re.sub(r"\(\d+(,\d+)?\)", "", m.group(2)).strip()
            if typ not in PARSE:
                raise SystemExit(f"schema.sql: no mapping for type {typ!r}")
            cur.append((m.group(1), typ))
        if line.startswith(");"):
            cur = None
    return out


HISTORY_COLUMNS = {"result_history", "settings_history"}   # copied to archive, never written to live (row 24)
SCHEMA = {k: [c for c in v if c[0] not in HISTORY_COLUMNS] for k, v in read_schema().items()}
TOPICS = [f"lab.{s}.{t}" for s, t in SCHEMA]
# silver: one table per source table name, its columns the union of both environments' (dev has a few more)
SILVER = {}
for (s, t), cols in SCHEMA.items():
    merged = SILVER.setdefault(t, {})
    for name, typ in cols:
        merged.setdefault(name, typ)

spark = session("lab-stream")
spark.conf.set("spark.sql.session.timeZone", "UTC")
for ns in ("bronze", "silver"):
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{ns}")


def bronze_table(topic):
    _, s, t = topic.split(".")
    return f"{CATALOG}.bronze.{s}_{t}"


def ensure_tables():
    for topic in TOPICS:
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {bronze_table(topic)} (
            key STRING, value STRING, op STRING, lsn BIGINT, source_ts_ms BIGINT,
            kafka_partition INT, kafka_offset BIGINT, kafka_timestamp TIMESTAMP, batch_id BIGINT) USING iceberg""")
    for t, cols in SILVER.items():
        spark_types = {"character varying": "STRING", "text": "STRING", "jsonb": "STRING", "tsvector": "STRING",
                       "integer": "INT", "smallint": "SMALLINT", "bigint": "BIGINT", "double precision": "DOUBLE",
                       "boolean": "BOOLEAN", "text[]": "ARRAY<STRING>", "timestamp without time zone": "TIMESTAMP",
                       "timestamp with time zone": "TIMESTAMP", "date": "DATE"}
        body = ", ".join(f"`{c}` {spark_types[typ]}" for c, typ in cols.items())
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.silver.{t} (env STRING, {body},
            _op STRING, _lsn BIGINT, _source_ts_ms BIGINT, _is_deleted BOOLEAN) USING iceberg
            TBLPROPERTIES ('format-version' = '2')""")
        # merge-on-read: a MERGE writes small delete files instead of rewriting whole data files (a template row
        # is up to 0.7 MB); the maintenance run compacts them
        spark.sql(f"""ALTER TABLE {CATALOG}.silver.{t} SET TBLPROPERTIES ('write.merge.mode' = 'merge-on-read',
            'write.update.mode' = 'merge-on-read', 'write.delete.mode' = 'merge-on-read')""")


def last_batch(table):
    rows = spark.sql(f"SELECT summary['lab.batch-id'] FROM {table}.snapshots ORDER BY committed_at DESC LIMIT 1").collect()
    return int(rows[0][0]) if rows and rows[0][0] is not None else -1


def to_silver(events, t):
    """The newest event per (env, id) of one source table, as silver rows."""
    cols = SILVER[t]
    schema = T.StructType([T.StructField(c, PARSE[typ][0]) for c, typ in cols.items()])
    known = set(cols)
    ev = (events.withColumn("env", F.regexp_extract("topic", r"^lab\.(dev|stg)_", 1))
          .withColumn("row", F.when(F.col("op") == "d", F.get_json_object("value", "$.before"))
                      .otherwise(F.get_json_object("value", "$.after"))))
    # a column Debezium sends that schema.sql does not know fails the batch (no silent schema drift)
    sample = ev.select(F.explode(F.json_object_keys("row")).alias("k")).distinct().collect()
    unknown = sorted({r.k for r in sample} - known)
    if unknown:
        raise RuntimeError(f"{t}: columns not in schema.sql: {unknown}")
    parsed = ev.withColumn("r", F.from_json("row", schema))
    out = [F.col("env")]
    for c, typ in cols.items():
        conv = PARSE[typ][1]
        col = F.col(f"r.`{c}`")
        out.append((conv(col) if conv else col).alias(c))
    out += [F.col("op").alias("_op"), F.col("lsn").alias("_lsn"), F.col("source_ts_ms").alias("_source_ts_ms"),
            (F.col("op") == "d").alias("_is_deleted")]
    rows = parsed.select(*out)
    newest = Window.partitionBy("env", "id").orderBy(F.desc("_lsn"))
    return rows.withColumn("_n", F.row_number().over(newest)).where("_n = 1").drop("_n")


def merge_silver(updates, t):
    # (`_deleted` is reserved by Iceberg for its own row deletes, hence `_is_deleted`)
    # a micro-batch's DataFrame lives in the streaming query's own session: its view, and the MERGE, must too
    ss = updates.sparkSession
    updates.createOrReplaceTempView("updates")
    cols = ["env", *SILVER[t], "_op", "_lsn", "_source_ts_ms", "_is_deleted"]
    sets = ", ".join(f"t.`{c}` = CASE WHEN s._is_deleted THEN t.`{c}` ELSE s.`{c}` END" if c in SILVER[t] and c != "id"
                     else f"t.`{c}` = s.`{c}`" for c in cols if c not in ("env", "id"))
    ss.sql(f"""MERGE INTO {CATALOG}.silver.{t} t USING updates s
        ON t.env = s.env AND t.id = s.id
        WHEN MATCHED AND s._lsn > t._lsn THEN UPDATE SET {sets}
        WHEN NOT MATCHED THEN INSERT ({", ".join(f"`{c}`" for c in cols)}) VALUES ({", ".join(f"s.`{c}`" for c in cols)})""")


def rebuild_pdf():
    spark.sql(f"""CREATE OR REPLACE TABLE {CATALOG}.silver.pdf USING iceberg AS
        SELECT content_hash, min(created_at) AS first_seen, sort_array(collect_set(env)) AS envs,
               count(*) AS documents FROM {CATALOG}.silver.document
        WHERE content_hash IS NOT NULL AND content_hash != '' AND NOT _is_deleted GROUP BY content_hash""")


def batch(df, batch_id):
    events = (df.select(
        F.col("topic"), F.col("key").cast("string").alias("key"), F.col("value").cast("string").alias("value"),
        F.col("partition").alias("kafka_partition"), F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_timestamp"))
        .where(F.col("value").isNotNull())
        .withColumn("op", F.get_json_object("value", "$.op"))
        .withColumn("lsn", F.get_json_object("value", "$.source.lsn").cast("long"))
        .withColumn("source_ts_ms", F.get_json_object("value", "$.source.ts_ms").cast("long"))
        .withColumn("batch_id", F.lit(batch_id).cast("long"))).persist(StorageLevel.DISK_ONLY)
    topics = sorted(r.topic for r in events.select("topic").distinct().collect())
    for topic in topics:                                   # bronze first: every event, once per batch id
        table = bronze_table(topic)
        if last_batch(table) >= batch_id:
            continue
        (events.where(F.col("topic") == topic).drop("topic").writeTo(table)
         .option("snapshot-property.lab.batch-id", str(batch_id)).append())
    for t in sorted({tp.split(".")[2] for tp in topics}):  # then silver: both environments of one table
        part = events.where(F.col("topic").isin(f"lab.dev_svc.{t}", f"lab.stg_svc.{t}",
                                                f"lab.dev_odoo.{t}", f"lab.stg_odoo.{t}"))
        merge_silver(to_silver(part, t), t)
    if "document" in {tp.split(".")[2] for tp in topics}:
        rebuild_pdf()
    n = events.count()
    events.unpersist()
    print(f"batch {batch_id}: {n} events, {len(topics)} topics", flush=True)


ensure_tables()
if spark.table(f"{CATALOG}.silver.document").limit(1).count():
    rebuild_pdf()               # from silver.document as it is now, before the first batch
stream = (spark.readStream.format("kafka")
          .option("kafka.bootstrap.servers", BOOTSTRAP)
          .option("subscribe", ",".join(TOPICS))
          .option("startingOffsets", "earliest")
          .option("maxOffsetsPerTrigger", MAX_EVENTS_PER_BATCH)
          .option("failOnDataLoss", "true")
          .load())
query = (stream.writeStream.foreachBatch(batch).option("checkpointLocation", CHECKPOINT)
         .trigger(processingTime=TRIGGER).start())
query.awaitTermination()
