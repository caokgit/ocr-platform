# Sizing a Spark pod on Kubernetes: heap plus overhead

A design note: why Spark's pods were `OOMKilled` on the lab's first full fill, what a pod's memory limit is made of,
and how the sizes were fixed without raising the lab's memory budget. The catalog the stream commits to is described
in the [JDBC catalog](iceberg-jdbc-catalog.md) note.

**The one idea: the limit that kills a Spark executor on Kubernetes is its pod's memory limit, which Spark sets as the
Java heap plus the overhead; the kernel kills the container when its memory use passes that limit, even while the
heap has room. So the overhead is not a rounding margin: it holds the JVM's own memory and, for a PySpark driver, the Python
process.**

## What the pod limit is made of

"spark.executor.memoryOverhead: Amount of additional memory to be allocated per executor process ... This is memory
that accounts for things like VM overheads, interned strings, other native overheads"
([Spark configuration](https://spark.apache.org/docs/latest/configuration.html)).

```text
 executor pod limit = spark.executor.memory  +  spark.executor.memoryOverhead
                      (the Java heap: rows,      (outside the heap: JVM threads, metaspace,
                       joins, caches)             network and compression buffers)

 a Java OutOfMemoryError = the heap is full
 OOMKilled               = heap + everything else passed the pod limit; the kernel ends the container
```

The driver has the same two parts, and in a PySpark job its overhead also holds the Python process that runs the job.

## The first fill, start by start

On 2026-11-01, the streaming job (Kafka to Iceberg bronze and silver) took six starts during the first full fill, the
first replay of the client's whole history through the pipeline.
Each failed start retried its unfinished batch from the checkpoint, so nothing was lost or written twice
([the outcomes](../../README.md#the-outcomes-so-far)). Three failed on memory, and the sixth held:

| Start | What happened | Change |
|---|---|---|
| 3 | Executors `OOMKilled`, 8 in 6 minutes; 1 GiB heap + 384 MiB overhead, 20,000-event batches, a copy-on-write MERGE rewriting a large file | Merge-on-read silver, 5,000-event batches, executor 1.5 GiB + 512 MiB |
| 4 | Executors still `OOMKilled`, the pod at 1,875 of 2,048 MiB in a shuffle | Same 2 GiB, split differently: 1 GiB + 1 GiB, 8 shuffle partitions instead of 200 |
| 5 | The driver `OOMKilled` (exit 137) at 640 MiB + 384 MiB: its overhead also holds the Python process, and the job's history (Spark's record of past jobs, stages and tasks, kept in the driver) grows | Driver 512 MiB + 640 MiB; the executor gives 128 MiB of overhead to it, 1 GiB + 896 MiB; the history capped |
| 6 | None: executor 1,459 to 1,600 MiB, driver 806 to 993 MiB | |

Starts 1 and 2 were code errors (the Spark session a MERGE statement ran in, a column name Iceberg reserves), fixed
the same evening.

## Why the total stayed, and the split changed

The pod at 1,875 MiB of 2,048 with a 1.5 GiB heap said where the pressure was: outside the heap. A bigger heap with
the same overhead raises the limit by the same amount and leaves the memory outside the heap no more room; a bigger
overhead inside the same total fixed it. Spark's total, driver and executor, stayed at 3 GiB. The final sizes, in
[sparkapp.yaml](../../pipelines/lake/k8s/sparkapp.yaml):

| Pod | Heap | Overhead | Limit | Seen at start 6 |
|---|---|---|---|---|
| Driver | 512 MiB | 640 MiB | 1,152 MiB | 806 to 993 MiB |
| Executor | 1 GiB | 896 MiB | 1,920 MiB | 1,459 to 1,600 MiB |

Raising the total was possible but not free. The data path's namespace has a quota of 8 GiB of memory limits: the
always-on pods take 4,864 MiB, and with Spark's 3 GiB and the replayer it is exactly 8 GiB; the machine's free memory
swings with the AI team's work. A larger executor would have meant a larger quota (a spec change) and a higher
free-memory check before each start, for a problem the split solved.

## In this lab

The budget is the [data path spec's box budget](../specs/data-path.md#box-budget); the fill and its checks are
[data path, step 4](../runbooks/data-path.md#4-fill-live-and-the-lake-box).
