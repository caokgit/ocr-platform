# Object storage for the lakehouse: S3, Azure Blob and SeaweedFS

A design note: what an object store is, why Iceberg fits it, how Azure Blob relates to S3, and why the lab's store is
SeaweedFS. The catalog that points into it is the [JDBC catalog](iceberg-jdbc-catalog.md).

**The one idea: an object store is one flat list of keys, each naming a whole object, read and written over HTTP;
nothing is renamed or edited in place. Iceberg never renames or edits a file, it only adds new ones and moves one
pointer, so any store that speaks S3 can hold the lakehouse. The lab's is SeaweedFS.**

## Buckets of keys over HTTP

"An object is a file and any metadata that describes the file. A bucket is a container for objects"; "Each object
has a key (or key name), which is the unique identifier for the object within the bucket"
([What is Amazon S3?](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)). The interface is a
handful of HTTP calls on keys: `PUT` a whole object, `GET` it, `LIST` keys under a prefix, `DELETE`. Many stores
speak that same interface, so `s3://` in this lab means SeaweedFS's S3 endpoint, not Amazon.

A bucket is not a tree of folders. The slashes in a key are characters; "folders" are what a listing shows when it
cuts the keys sharing a prefix at the next slash: "prefixes are not directories"
([organizing objects using prefixes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-prefixes.html)).
The lab's bucket, `lab-lake`, as the store sees it (names shortened):

```text
 key                                                                     object
 datasets/ultralytics/2026-09-24-4a208a33d4ca/images/train/<page>.jpg     a page image of the labelled set
 splits/2026-09-24-4a208a33d4ca/test.txt                                 the page-region detector's test split
 warehouse/silver/match_candidate/data/00000-0-<uuid>-00001.parquet      rows
 warehouse/silver/match_candidate/metadata/00007-<uuid>.metadata.json    table metadata

 LIST prefix=""  delimiter="/"   ->  datasets/   splits/   warehouse/      ("folders": nothing exists at them)
```

| You want to | On a file system | On an object store |
|---|---|---|
| Rename a folder | One atomic rename | Copy every object to a new key, then delete the old ones: not atomic |
| Change a file | Write into it | Upload the whole object again |
| Make an empty folder | `mkdir` | Nothing to make: the prefix appears with its first key |

That table is why Iceberg suits an object store: a commit only adds new keys and moves one pointer in the catalog.

## Azure Blob: the same model, unless the namespace is on

The client's own storage is Azure Blob, so the same model, by other names, applies there. A Blob container with the hierarchical namespace off is a flat list of names, exactly like a bucket: "By default, the
Blob service is based on a flat storage scheme, not a hierarchical scheme. However, you may specify a character or
string delimiter within a blob name to create a virtual hierarchy"
([naming containers and blobs](https://learn.microsoft.com/en-us/rest/api/storageservices/naming-and-referencing-containers--blobs--and-metadata)).
The blob name plays the key's role.

| | Azure Blob, namespace off | S3 | This lab |
|---|---|---|---|
| Container of objects | Container | Bucket | `lab-lake` |
| One object's name | Blob name, slashes allowed | Key | `warehouse/silver/...parquet` |
| "Folder" | A shared prefix | Prefix | Prefix |

ADLS Gen2 is the same storage account with the namespace switched on, which adds real directories: a hierarchical
namespace "processes these tasks by updating a single entry (the parent directory)", and "Tools like Hive and Spark
often write output to temporary locations and then rename the location at the conclusion of the job"
([hierarchical namespace](https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-namespace)).
A table format that commits by renaming needs that; Iceberg does not, which is part of why it fits a plain S3 store.

## Why SeaweedFS

The object store was first planned as MinIO. By the time the data path was specified, MinIO's community edition was no
longer a maintained open-source option:

| Date | What changed | Source |
|---|---|---|
| 2025-10-15 | "The MinIO community edition is now distributed as source code only. We will no longer provide pre-compiled binary releases" | [MinIO README](https://github.com/minio/minio/blob/master/README.md) |
| 2025-12-03 | "This project is currently under maintenance and is not accepting new changes" | [README at 27742d46](https://raw.githubusercontent.com/minio/minio/27742d46/README.md) |
| By 2026-10-31 | The repository archived ("THIS REPOSITORY IS NO LONGER MAINTAINED") | [GitHub API](https://api.github.com/repos/minio/minio) |

The maintained stores that run on Kubernetes from a Helm chart, compared on 2026-10-31 against the lab's three
criteria: an Apache-2.0 licence, a chart repository, and Spark in the project's own testing:

| Store | Licence | Helm chart | Notes |
|---|---|---|---|
| **SeaweedFS** | Apache-2.0 | A chart repository | One all-in-one pod; "Spark integration tests run in CI on every change" ([README](https://github.com/seaweedfs/seaweedfs)) |
| Garage | AGPL-3.0 | In its repository only | No object versioning ([compatibility](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/)) |
| Ceph RGW (Rook) | Apache-2.0 | A chart repository | Needs raw devices, partitions or block volumes |
| RustFS | Apache-2.0 | In its repository only | Young: 1.0 in 2026 |
| Versity S3 Gateway | Apache-2.0 | In its repository only | Serves a local folder over S3 |

SeaweedFS runs as one all-in-one pod, installed by Argo CD from its chart, its S3 endpoint a Service on port 8333
inside the cluster. It holds the Iceberg warehouse, the copy of the labelled pages and the test split; the client's
own Azure storage is never written to.

## In this lab

The store is row 13 of the [data path spec](../specs/data-path.md#decisions) and its
[object store section](../specs/data-path.md#object-store); its install is
[data path, step 2](../runbooks/data-path.md#2-install-the-data-path-box).
