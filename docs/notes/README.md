# Design notes

Each note settles one engineering question the lab met, with the lab's real values and the decision it led to. They
are written from what was built and measured; the [README](../../README.md) says what the lab delivers, and
[How I work](../how-i-work.md) says how.

| # | Note | The question it settles |
|---|---|---|
| 1 | [Ansible for the machine, Argo CD for the cluster](ansible-and-argo-cd.md) | Which tool owns which layer, and where they hand over |
| 2 | [Two paths to the cluster: GitOps and direct runs](gitops-and-direct-runs.md) | What reaches the cluster through Git, what does not, and how a run stays traceable to its code |
| 3 | [Kubernetes on a machine another team uses](kubernetes-on-a-shared-machine.md) | How a cluster shares a machine with another team's workloads: only during sessions, first in the firewall, the API through a tunnel, no trace left |
| 4 | [The WAL, the slot and Debezium](wal-slot-debezium.md) | Who holds Postgres's log in change data capture, why no slot goes on a shared database, and why an idle database needs a heartbeat |
| 5 | [An Iceberg catalog in Postgres: the JDBC catalog](iceberg-jdbc-catalog.md) | What a lakehouse catalog must do, why one table in an existing Postgres does it, and why its cache was turned off |
| 6 | [Object storage for the lakehouse: S3, Azure Blob and SeaweedFS](object-storage.md) | What an object store is, why Iceberg fits it, and why SeaweedFS after MinIO's community edition was archived |
| 7 | [Sizing a Spark pod on Kubernetes: heap plus overhead](spark-pod-memory.md) | Why Spark pods were `OOMKilled` with room in the heap, and how the sizes were fixed inside the same budget |
| 8 | [GPUs in Kubernetes on the machine's own driver](gpus-on-the-hosts-driver.md) | How a cluster schedules GPUs that another team's Docker already uses, without a second driver, and what Kubernetes cannot see |
| 9 | [Reaching a lab machine from WSL through a full-tunnel VPN](wsl-and-a-full-tunnel-vpn.md) | Why WSL lost its packets with the office VPN on, and the two changes that made the agent and the machine reachable |
