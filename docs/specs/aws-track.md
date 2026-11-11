# Spec: the AWS track (EKS, Terraform, operations drills)

How the lab's platform moves from k3s on one box to AWS: Terraform for the account (network, identity, storage,
database, EKS, Karpenter), a per-cluster overlay so the same Argo CD apps run on kind and on EKS, and drills for the
operations work a platform needs: autoscaling, spot interruptions, database upgrade and restore, alerts that find a fault,
safe releases, cost and Git flow. No AWS account is used: Terraform is applied to LocalStack where it emulates the
service and to a mocked provider where it does not, and the cluster side runs on kind. How to run it:
[runbooks/aws-track.md](../runbooks/aws-track.md). It builds on the [phase 1 platform](gpu-box-platform.md) and
reuses the [data path's](data-path.md) operators; it implements [D18](../design.md#decisions).

**State: approved on 2026-11-03 and built on 2026-11-04.** C1 to C18 passed as worded, with their output in the
[runbook](../runbooks/aws-track.md); C19 is this repo's CI and C20 the gate this export passed. Changes made during
the build, in the spec first: decision 14 moved to Kyverno's `ValidatingPolicy` (CEL),
decision 19's cutover uses one pooler per cluster and a Service between them (a Pooler's cluster cannot change),
decision 23 made Kyverno, KEDA, Argo Rollouts and the database operators per-drill on kind.

## Decisions

**Everything is real or says it is not:** a check that ran shows its output in the runbook; what could not run
without an account is named as such.

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Where does Terraform run without an AWS account? | **LocalStack 4.14.0** for the services its free image has (VPC, IAM, S3, KMS, SQS, EventBridge, Secrets Manager); **`terraform test` with `mock_provider`** for every module, including RDS and EKS | The last token-free LocalStack image; the mock covers what it lacks |
| 2 | Region | `ap-southeast-1` | Closest AWS region to the lab |
| 3 | Terraform layout | `infra/aws/terraform/modules/<name>` (kms, network, iam, storage, database, eks, karpenter), `envs/dev` (the full design), `envs/localstack` (the emulated subset); tests next to each module | One module per concern; an env is only a composition |
| 4 | State | S3 backend with `use_lockfile` in `envs/dev`; local state for `envs/localstack` | Native S3 locking, no DynamoDB table |
| 5 | Network | One VPC `10.40.0.0/16`, three AZs, public, private and database subnets per AZ; one NAT gateway in dev (`single_nat_gateway`, per-AZ when false); S3 gateway endpoint | NAT per AZ costs three times as much; the switch shows the trade-off |
| 6 | Identity for pods | **EKS Pod Identity** roles per workload: `external-secrets` (read one Secrets Manager path), `cert-manager` (DNS-01 records in one Route 53 zone), `lake-writer` (the lake bucket), `karpenter` (its controller policy); access entries for people. The API endpoint is private by default: operators reach it from inside the VPC (a VPN or a bastion, not part of this design) or from an allowed range | No OIDC provider per cluster, no keys |
| 7 | Encryption | One customer-managed KMS key, rotation on, for S3, RDS, Secrets Manager and EKS secrets | One key to audit |
| 8 | Database | RDS for PostgreSQL 17, `db.t4g.medium`, Multi-AZ switch, master password managed by RDS in Secrets Manager, a parameter group with `rds.logical_replication = 1`, 7-day backups, deletion protection | Logical replication is what CDC and low-downtime upgrades need |
| 9 | EKS | Version 1.35, API authentication mode, a managed node group `system` (on-demand, 2 x `m7i.large`) for CoreDNS, Karpenter and Argo CD; add-ons vpc-cni, coredns, kube-proxy, eks-pod-identity-agent, aws-ebs-csi-driver | System pods must not sit on spot |
| 10 | Karpenter | NodePools `spot` (weight 100) and `on-demand` (weight 10) on one EC2NodeClass; consolidation `WhenEmptyOrUnderutilized`; disruption budgets of 20% (spot) and 10% (on-demand); an SQS interruption queue fed by four EventBridge rules | Spot first, on-demand when spot is short |
| 11 | GitOps across clusters | The existing Argo CD app of apps; per cluster, a root app and an ApplicationSet of the add-ons in `infra/argocd/clusters/<kind\|eks>/apps/`, Helm values in `infra/platform/values/<addon>/` (`common.yaml` plus the cluster's file), cluster-wide objects as a Kustomize base with a `kind` and an `eks` overlay. On kind, Argo CD reads a local `git daemon` (no credentials) | Same objects everywhere; the overlay is the only difference |
| 12 | Traffic and TLS | Gateway API with Envoy Gateway, its Service an NLB on EKS (an `EnvoyProxy` with the NLB annotation); cert-manager: a self-signed CA on kind, Let's Encrypt DNS-01 in Route 53 on EKS | ingress-nginx is retired upstream |
| 13 | Secrets | External Secrets Operator; a `ClusterSecretStore` on AWS Secrets Manager (LocalStack endpoint on kind, Pod Identity on EKS) | No secret in Git |
| 14 | Policy | Kyverno `ValidatingPolicy` (CEL): `require-requests-limits` and `disallow-latest-tag` denied in the demo namespaces, `require-run-as-non-root` in audit | Shows enforce and audit side by side; `ClusterPolicy` is deprecated in Kyverno 1.19 |
| 15 | Demo workload | podinfo (a small Go web app with Prometheus metrics and fault switches) as the API; a small SQS worker for KEDA | Real metrics and a real fault without writing an app |
| 16 | Autoscaling | HPA on CPU 60% for podinfo (1 to 6), driven by k6; KEDA `aws-sqs-queue` scaler for the worker (0 to 5, 10 messages each); Karpenter on KWOK nodes | Pods by load, workers by waiting work, nodes by pods that do not fit |
| 17 | Releases | Argo Rollouts canary 20%, 50%, 100% with a Prometheus `AnalysisTemplate` (5xx share under 1%); replica-weighted, no traffic router | A bad version aborts by itself; a mesh adds nothing at this size |
| 18 | Observability | kube-prometheus-stack, Loki single binary with Grafana Alloy; alert rules as `PrometheusRule`; Alertmanager posts to an in-cluster webhook sink that logs every notification with its time | The sink makes the alert's timing measurable |
| 19 | Database drills | CloudNativePG on kind: PG 16 to PG 17 by `Publication` and `Subscription`, cutover by moving a Service from pg16's PgBouncer `Pooler` to pg17's; `instances: 2` for the replica and a failover; Barman Cloud plugin backups to LocalStack S3 and a point-in-time restore | Replaces a dump-and-restore, where writes stop for the whole copy, with a measured cutover |
| 20 | Cost | A script reads the AWS public price list and the Spot Advisor data for the design's resources; the estimate is a doc with every price dated ([the estimate](../aws-cost-estimate.md)) | No account needed to price the design |
| 21 | CI | GitHub Actions: fmt, validate, tflint, `terraform test`, Trivy, kustomize + helm render with kubeconform, docs check, gitleaks. **Each job checks only what a change can break** (2026-11-11): on a pull request, the first step of `terraform` and `manifests` asks [tools/ci-paths.sh](../../tools/ci-paths.sh) whether the change touches a path its check reads, and the rest of the job is skipped when it does not; the job still runs and reports, so the ruleset's required checks are unchanged. `docs-and-secrets` always runs. Every push to `main` and a weekly run check everything | Every check here runs without credentials. A docs-only pull request waited about 2 min for checks with nothing to check (PR #4, 2026-11-11). The skip sits inside each job because a workflow skipped by a path filter never reports its required check, which blocks the merge, and a job skipped because a job it needs failed counts as passed; a decision step that fails, fails its job. The weekly run catches a pinned download or a ruleset that broke outside the repo |
| 22 | Git flow | Trunk-based on the public repo: a ruleset on `main` (PR, green checks, no force push or deletion), CODEOWNERS, a PR template, `v*` tags with release notes | One maintainer |
| 23 | The laptop's memory (7.5 GB) | One kind cluster with one node; a base set always on (Argo CD, Envoy Gateway, cert-manager, ESO, metrics-server, monitoring, Loki); each drill's extra parts installed for the drill and removed after it | The whole set at once does not fit |

## Layout

| Path | Holds |
|---|---|
| `infra/aws/terraform/modules/*` | One module per concern, each with `tests/*.tftest.hcl` |
| `infra/aws/terraform/envs/dev` | The full AWS design, planned only |
| `infra/aws/terraform/envs/localstack` | network, iam, storage, the Karpenter queue and a secret, applied to LocalStack |
| `infra/aws/cost/` | The price-list script |
| `infra/kind/` | The kind cluster config, the local Git and LocalStack helpers |
| `infra/argocd/clusters/{kind,eks}/` | Each cluster's root app and ApplicationSet; `kind/optional/` the per-drill add-ons |
| `infra/platform/values/<addon>/` | `common.yaml`, `kind.yaml`, `eks.yaml` |
| `infra/platform/manifests/` | `base`, `kind`, `eks`, `policies`: issuers, the secret store, policies, NodePools, the Gateway |
| `infra/drills/<name>/` | Each drill's workload and scripts |
| `.github/` | CI, CODEOWNERS, PR template, the ruleset as JSON |

## Acceptance

| # | Check | Passes when |
|---|---|---|
| C1 | Static | `terraform fmt -check` and `validate` clean on every module and env; tflint clean with the AWS ruleset |
| C2 | Security scan | Trivy config scan: no HIGH or CRITICAL finding unless listed with its reason in `.trivyignore` |
| C3 | Mocked apply | `terraform test` passes for every module and for `envs/dev` |
| C4 | Emulated apply | `envs/localstack` applies; a second plan shows no changes; destroy leaves nothing |
| C5 | EKS overlay | `kustomize build` of the eks overlay and `helm template` of every add-on with its eks values pass kubeconform |
| C6 | kind platform | Every Application on kind `Synced` and `Healthy` |
| C7 | HTTPS in | podinfo answers through the Gateway over HTTPS with a certificate from the lab CA |
| C8 | Secret from AWS | A value written to Secrets Manager (LocalStack) appears in the Kubernetes Secret; a changed value arrives within the refresh interval |
| C9 | Policy | A `:latest` pod in a demo namespace is rejected; an audit result is reported for a root pod |
| C10 | HPA | Under k6 load, podinfo goes from 1 to at least 4 replicas and back to 1 after the load; times recorded |
| C11 | KEDA | 200 messages scale the worker from 0 to 5; the queue drains; the worker returns to 0 |
| C12 | Karpenter | Pending pods get KWOK nodes from the `spot` pool first; when spot is unavailable, `on-demand`; a disrupted spot node is drained with the PodDisruptionBudget held (never fewer than the minimum ready) |
| C13 | Major upgrade | PG 16 to PG 17 by logical replication under continuous writes: row counts and a checksum match; the client-side write gap at cutover recorded (target under 10 s) |
| C14 | Failover | Deleting the primary pod promotes the replica; the client-side write gap recorded |
| C15 | Point-in-time restore | After an accidental `DELETE`, a new cluster restored to a second before it has the rows back |
| C16 | Alert finds the fault | A fault injected in podinfo fires an alert in Alertmanager (time to fire recorded), the logs in Loki show the failing requests, and the alert resolves after the fix |
| C17 | Canary | A faulty version is aborted by the analysis and rolled back; a good one is promoted |
| C18 | Cost | Every price in the estimate traces to a price file and its date |
| C19 | CI | The workflow is green on GitHub. On a pull request that changes no path a job checks, that job reports success with its checks skipped; on one that changes the workflow or the decision script, every job runs; the decision script fails, never skips, when it cannot read the change |
| C20 | Export | The export's search gate exits 0 (private terms, addresses, gitleaks) |

## Not chosen

| Option | Why not |
|---|---|
| A real AWS account | None is available; the design is applied as far as the emulator and the mock allow, and the README says so |
| Terragrunt | One env; plain modules and env folders are clearer |
| Istio or another mesh for the canary | Replica weighting is enough to show analysis-driven rollback |
| ingress-nginx | Retired upstream |
| Velero | CloudNativePG's own backups cover the database; the rest is in Git |
| SonarQube, OWASP ZAP | No application code of the lab's own to scan |
| MySQL to PostgreSQL with DMS | DMS needs an account; the PG 16 to 17 move shows the same replication-based cutover |
