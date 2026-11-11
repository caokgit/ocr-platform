# Two paths to the cluster: GitOps and direct runs

A design note: which changes reach the cluster through Git, which come straight from the laptop, and how a run started
from the laptop stays traceable to its code. It builds on [the handoff](ansible-and-argo-cd.md).

**The one idea: changes reach the machine by two paths, through Git or straight from the laptop. Only Argo CD's path
goes through GitHub, so its changes wait for a push. Everything started from the laptop (the launchers and
`kubectl apply` to the Kubernetes API, the playbooks over SSH to the host) arrives at once, from the laptop's working
copy, pushed or not. So since 2026-11-02 every launcher stamps its run with the commit it came from.**

## The two paths

```text
 laptop working copy ──commit──push──> GitHub main ──(Argo CD pulls every 3 min)──> cluster   infra/argocd/
        │
        └──── SSH tunnel ──> Kubernetes API ──────────────────────────────────────> cluster   launchers, kubectl apply
        └──── SSH ─────────> the machine's OS (Ansible) ──────────────────────────> host      lab-up, lab-down
```

**Why Argo CD owns no runs.** A replay or a Spark job is a new, uniquely named object holding the laptop's code, made
to run once or until I stop it. Argo CD keeps the cluster equal to Git with self-heal on, so a stream stopped by
deleting it would be recreated. The long-running services (Postgres, Kafka, Debezium, SeaweedFS and their operators)
come from Git; the runs come from the laptop's launchers, which put the code in a ConfigMap, fill in the
`SparkApplication` or Job, and create it.

## One evening, both paths

On 2026-11-01, installing the data path and then filling it for the first time
([data path, steps 2 and 4](../runbooks/data-path.md#2-install-the-data-path-box)), fixes reached the cluster by both
paths, in this order:

| Fix | Path | Reached the cluster | Reached GitHub |
|---|---|---|---|
| The Postgres roles' default fields (Argo CD showed `OutOfSync`) | Git | After the push; every app found `Synced` minutes later | With the push |
| Debezium's absolute offset path | `kubectl apply` by hand | At once | Pushed later that evening; Argo CD then adopted the identical object |
| The streaming job: the Spark session its MERGE ran in, the delete-marker column's name (reserved by Iceberg), memory three times, the catalog cache | The lake launcher, at each stream start (code in its ConfigMap, sizes in the `SparkApplication`) | Seconds after each edit, six starts in half an hour | Committed and pushed later that evening |

So for a while the cluster ran code that GitHub did not yet hold. Every change was committed in the end, but that
evening nothing on the cluster said which commit a job ran. That is a lineage gap: a result could not be traced back
to the exact code that made it.

## The fix: a commit stamp on every run

Since 2026-11-02, the launchers label every Job and `SparkApplication` they create, and their pods, with two labels:
the commit the laptop was at, and whether the launcher's folder had uncommitted changes.

```text
lab/git-commit = <the commit the laptop was at>
lab/git-dirty  = true | false        (uncommitted changes under the launcher's folder)
```

A run labelled clean ran exactly that commit's code. One labelled dirty ran a working copy that Git may never hold
as such, which is exactly the case the evening above produced. The stamp was checked offline, with `kubectl` stubbed
to capture what the launchers send. The first run on the cluster will read it back with
`kubectl get jobs,sparkapplications -L lab/git-commit`.

## In this lab

The split between services from Git and runs from the laptop, and the stamp, are in the
[data path spec's layout](../specs/data-path.md#layout); the launchers are
[pipelines/replay/launch.py](../../pipelines/replay/launch.py) and
[pipelines/lake/launch.py](../../pipelines/lake/launch.py). The same idea, every output traceable to what made it,
is outcome T7 ([the outcomes](../../README.md#outcomes)).
