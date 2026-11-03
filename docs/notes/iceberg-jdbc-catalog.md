# An Iceberg catalog in Postgres: the JDBC catalog

A design note: what Iceberg needs a catalog for, why the lab keeps it in the Postgres it already runs, and the stale
read that taught it to turn the catalog's cache off. The tables it serves sit in
[object storage](object-storage.md).

**The one idea: an Iceberg table is a set of immutable files plus one pointer to its current metadata file, and the
catalog's only hard job is to move that pointer atomically. A SQL database does that in one statement, so the lab's
catalog is one table in the Postgres it already runs, reached through JDBC: no extra service.**

## What a commit needs

Every write to an Iceberg table (a streaming batch, a gold build) writes new data and metadata files, then commits by
moving the table's pointer from the old metadata file to the new one, but only if nobody moved it first. Iceberg's spec
asks nothing more of a catalog: "storing a pointer in a metastore or database that is updated with a check-and-put
operation" ([Iceberg spec](https://iceberg.apache.org/spec/)).

The JDBC catalog, which ships with Iceberg, keeps those pointers in one table, `iceberg_tables`, and commits with one
statement (from [`JdbcUtil.java`](https://github.com/apache/iceberg/blob/apache-iceberg-1.12.0/core/src/main/java/org/apache/iceberg/jdbc/JdbcUtil.java),
trimmed):

```sql
UPDATE iceberg_tables
   SET metadata_location = <new file>, previous_metadata_location = <old file>
 WHERE catalog_name = 'lab' AND table_namespace = 'silver' AND table_name = 'match_candidate'
   AND metadata_location = <old file>;      -- the check: still the file this writer started from?
```

One row changed: the commit won. Zero rows: another writer committed first; Iceberg raises, and the writer retries on
top of the new version.

## Why it is called JDBC

JDBC (Java Database Connectivity) is Java's standard way to talk to a SQL database: one API for the program, one
driver per database. Spark and Iceberg run on the JVM, so the catalog that keeps its pointers in a SQL database
reaches it through JDBC, and is named after it: "Iceberg supports using a table in a relational database to manage
Iceberg tables through JDBC. The database that JDBC connects to must support atomic transaction"
([JDBC catalog](https://iceberg.apache.org/docs/latest/jdbc/)).

```text
 Spark driver (a JVM)
   Iceberg JdbcCatalog          builds the UPDATE ... WHERE metadata_location = <old file>
   JDBC API (java.sql)          the same calls for every database: connect, execute, read the row count
   pgJDBC driver                the Postgres-specific part: one jar
     | Postgres wire protocol, TCP 5432
 lab-pg-rw service  ->  the lab's Postgres  ->  database catalog  ->  table iceberg_tables, 1 row changed
```

Only the pgJDBC driver knows Postgres. Here, JDBC carries only the pointer row; the data goes to the bucket over S3.
The main settings, as the lake jobs set them ([common.py](../../pipelines/lake/jobs/common.py), which also holds the
credentials' source and the S3 endpoint):

```text
spark.sql.catalog.lab.type           = jdbc
spark.sql.catalog.lab.uri            = jdbc:postgresql://lab-pg-rw:5432/catalog
spark.sql.catalog.lab.warehouse      = s3://lab-lake/warehouse/
spark.sql.catalog.lab.io-impl        = org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.lab.cache-enabled  = false
```

## Why not another catalog

| Catalog | What it would add to the lab |
|---|---|
| **JDBC, in the lab's Postgres** | One more database in a server that already runs for `archive` (the frozen copy of the client's tables) and `live` (where their history is replayed); a commit is one Postgres transaction |
| REST (Lakekeeper, Polaris) | One more server to run, secure and keep up |
| Hive | A metastore service |
| Glue | AWS's, and the lab runs on its own machine |
| Hadoop (files only) | No database, but its commit relies on a file rename, unsafe on an object store, which has none |

## The found error: a stale read through the catalog's cache

On 2026-11-01, after the first full fill (the first replay of the client's whole history), the check on `silver.pdf`
(one row per distinct PDF, rebuilt from `silver.document`) found **230 rows, not 232**, while every silver table, and
`silver.document` itself, matched the copy's row counts.

The streaming job is a long-running Spark session, and Iceberg's Spark catalog caches table metadata in it by default
("Whether to enable catalog cache, default value is true", [Iceberg Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/)).
The rebuild of `silver.pdf` read `silver.document` through that cache: a version older than the stream's latest
commits.

**The fix:** `cache-enabled = false`, so every read asks the catalog for the table's current pointer, one row in
Postgres, and the stream rebuilds `silver.pdf` when it starts. The check then read 232, and silver still
held all 239,880 rows after the stream resumed. A count off by two is a real bug, not noise.

## In this lab

The catalog choice is row 14 of the [data path spec](../specs/data-path.md#decisions), the cache setting in
[common.py](../../pipelines/lake/jobs/common.py); the count check is acceptance B5, in
[verify end to end](../runbooks/data-path.md#verify-end-to-end).
