"""The Spark session every lake job uses: the Iceberg catalog `lab` (JDBC, in the lab's Postgres) over the bucket
lab-lake on SeaweedFS (docs/specs/data-path.md#spark-and-the-catalog). Credentials come from the pod's environment,
set from cluster Secrets by the SparkApplication; none is in this file."""

import os

from pyspark.sql import SparkSession

CATALOG = "lab"


def session(app):
    c = f"spark.sql.catalog.{CATALOG}"
    return (SparkSession.builder.appName(app)
            .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
            .config(c, "org.apache.iceberg.spark.SparkCatalog")
            .config(f"{c}.type", "jdbc")
            .config(f"{c}.uri", "jdbc:postgresql://lab-pg-rw:5432/catalog")
            .config(f"{c}.jdbc.user", os.environ["CATALOG_USER"])
            .config(f"{c}.jdbc.password", os.environ["CATALOG_PASSWORD"])
            .config(f"{c}.warehouse", "s3://lab-lake/warehouse/")
            .config(f"{c}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
            .config(f"{c}.s3.endpoint", "http://seaweedfs-all-in-one:8333")
            .config(f"{c}.s3.path-style-access", "true")
            .config(f"{c}.cache-enabled", "false")   # a long-running stream must read each table's newest version
            .getOrCreate())
