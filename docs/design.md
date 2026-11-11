# Design

The source of truth for **what** this lab builds and **why**. How each part works lives in the code; this page links
to it once it exists. Read the [use case](use-case.md) first for the business; the [README](../README.md) says what is
built and what is planned.

## Context

I am a cloud, DevOps and data platform engineer. The lab builds an ML platform around a real workload: the OCR service
my team runs for its client, a garment manufacturer ([use case](use-case.md)). The workload is in daily use (the
client's staff work in its staging environment), and it has the gaps an ML platform closes: the
[problem statements](#problem-statements) below. The lab is built on a machine shared with the AI team, with the
client's real data, and the public repo shows the record without the data ([D2](#decisions), [D16](#decisions)).

**Who the platform is for.** A platform is built for the engineers who use it. Here they are my own engineering team:
the AI team that trains the detector and owns the prompts, and the engineers whose services call the OCR. The lab does
not simulate them. It stays **realistic**: their real models, data and constraints, and the interfaces they would use
(2026-11-11). So every spec from phase 2b on answers five questions:

1. **Who uses it, and through what?** For example, an AI engineer submits a training job, reads MLflow, or calls one
   OpenAI-compatible endpoint.
2. **On what real thing?** The production weights, the AI team's 2,041 labelled pages (2,040 copied; one image is missing at the source), the 200 human picks, the
   development GPT deployments in Microsoft Foundry.
3. **Under which real constraint?** Two RTX 3060s with 12 GB each, shared with the AI team's containers; the
   machine's free memory swinging by the hour.
4. **How does an engineer start using it?** A "use it" section in the runbook, one command per task.
5. **What does it measure against today?** Each result beside today's system.

## Problem statements

**The AI team's OCR models are trained by hand, judged by eye, served on CPU and changed by configuration, so nobody
can say whether a change made the OCR better or worse.** The nine problems, P1 to P9, each with its evidence and date,
are in the [README](../README.md#problem-statements); the full evidence is in
[the use case](use-case.md#where-it-falls-short-today).

## Outcomes

**The lab builds one platform that takes a versioned dataset to a model that is gated, served and observed, for the engineers who build
the models, and measures every step against today's system.** Each outcome is an acceptance criterion, shown on the
machine with the client's real data (2026-10-22; restated 2026-11-11). Not in scope: changing the client's
production; the results are a proposal the AI team can adopt. Where each outcome stands is in the
[README](../README.md#outcomes).

A target is a number, or a rule fixed in the phase spec **before** the run, never after it. A baseline not measured
yet names the phase that measures it first.

| # | Outcome | From | Metric | Baseline | Target | Phase | Decisions |
|---|---|---|---|---|---|---|---|
| T1 | Reproducible detector training | P1 | mAP@50 and recall on the frozen test split; a rerun's difference | The production weights on the test split: measured first in 2b | The production recipe within a tolerance stated in the 2b spec; a rerun gives the same numbers | 2b | [D14](#decisions), [D6](#decisions) |
| T2 | Gold sets and a scoreboard | P2 | One MLflow table of every detector, GPT and vision-language model version, each number with its interval | No test set; no comparison | A test split frozen by document, a human gold set, the table | 2a, 2b | [D6](#decisions) |
| T3 | Fewer GPT calls, by a self-hosted vision-language model behind the gateway | P5 | Share of elements answered without GPT at equal top-1 on the gold set; GPT calls and tokens per document | 28 calls, 488,836 input tokens for one 10-page document (2026-10-24); GPT's top-1 on the gold set: measured first in 3a | Set in the 3a spec | 3a | [D20](#decisions) |
| T4 | Versioned datasets from a CDC path | P4 | A replayed edit's time to silver, with no polling; a training run rebuilt from its snapshot id | No dataset can be rebuilt | Within 60 s; the rebuild gives the same dataset | 2a, 2b | [D5](#decisions) |
| T5 | GPU serving with measured trade-offs | P6 | mAP@50, recall, p50 and p95 latency and throughput per precision (FP32, FP16, INT8) | Today's CPU latency: measured first in 3a | The accuracy loss allowed per precision, set in the 3a spec | 3a | [D7](#decisions) |
| T6 | Serving and GPU observability | P9 | SLOs of serving and training; each alert proven by a drill | Logs to stderr only | Every alert fires in its drill and has a runbook row | 3c | [D8](#decisions) |
| T7 | One gate and full lineage | P3 | Changes blocked by the gate; outputs carrying their lineage | Weights versioned by file name only | A deliberately worse model and a worse prompt are both blocked; every output names its weights, prompt and deployment | 2b, 3a | [D15](#decisions) |
| T8 | Self-service training and serving | P7 | Steps for an AI engineer to train or call a model; what a second GPU job does | A person in a cloud web UI; nothing scheduling between GPU jobs | One command per task; a second job waits in the queue within its quota instead of sharing a GPU by accident | 2b, 3a | [D20](#decisions) |
| T9 | Past picks reused by retrieval | P8 | recall@k of the human-picked crop; retrieval p95; the effect on top-1 through the gate | No reuse | Set in the 3b spec | 3b | [D20](#decisions) |

## Decisions

| ID | Decision | Why | Decided |
|---|---|---|---|
| D1 | Build on the client's **garment-spec OCR** workload, not another LLM workload | OCR has a self-hosted model (YOLO) and a human correction loop with full version history in Odoo, but no automated evaluation, registry or retraining: a real MLOps gap I can own. The other workload calls a hosted model and already has an evaluation gate, so my contribution there would be thin | 2026-10-18 |
| D2 | The lab's repo stays **private**; the public showcase is a separate repo with fresh history | Git history keeps everything ever committed; flipping the lab's repo public would leak content edited out later. The export copies allowlisted paths and runs secret, address and name scans before a review | 2026-10-18 |
| D3 | The **Ubuntu GPU machine, shared with the AI team** (the lab runs when the machine is not tight on CPU and RAM, agreed 2026-10-23), runs a single-node **k3s** cluster; the laptop is the dev machine and kubectl client | Real GPU scheduling on Kubernetes, TensorRT numbers and fast training. Fallback: `kind` on the laptop, CPU only, after raising WSL memory to 10 GB (laptop: 16 GB host, WSL sees 7.5 GB, measured 2026-10-18) | 2026-10-18 |
| D4 | **Ansible** only for the machine's OS layer (prerequisites, k3s install and upgrade, kubeconfig, lab teardown), always previewed with `--check --diff`; everything in the cluster managed by **Argo CD** from the lab's repo as **Helm** charts; the NVIDIA driver is the host's own (610.43.02, already used by the AI team's Docker workloads), so the GPU Operator runs with its driver install off; how the rest of the GPU stack and k3s sit next to Docker is in the [platform spec](specs/gpu-box-platform.md#decisions) | Each layer gets its usual tool ([Ansible and Argo CD](notes/ansible-and-argo-cd.md)). Ansible's dry run is the "show every change first" rule built in; on-prem Kubernetes installs are still Ansible territory | 2026-10-18; scope refined 2026-10-19; the driver revised 2026-10-25 (it was "left to the GPU Operator", written before the machine was read, [why](notes/gpus-on-the-hosts-driver.md#the-first-design-and-what-reading-the-machine-changed)) |
| D5 | Data path on the **client's real data**: a read-only **snapshot** of the OCR tables (Odoo results and history, the service's runs, units and candidates; other OCR outputs come with the [D15](#decisions) extended phase) from the client's **development (dev) and staging (stg)** Postgres into a lab Postgres on the machine, **grouped by PDF content hash** in silver, the lakehouse's current-state layer (232 distinct PDFs instead of dev's 146, 2026-10-31), read through reader roles; a **replayer** re-writes that history in time order; then **Postgres** -> **Debezium** (slot on the lab copy only) -> **Kafka (Strimzi)** -> **Spark on K8s** -> bronze/silver **Iceberg** tables on **SeaweedFS** (MinIO's community edition is archived, [why](notes/object-storage.md#why-seaweedfs)) -> **gold** tables; the two environments merge in silver. The Iceberg snapshot id is the dataset version logged to MLflow (no DVC); how each stage works: the [2a spec](specs/data-path.md#decisions). Never a replication slot on the client's dev server | Exercises CDC, messaging, Spark and a lakehouse in an ML context; CDC captures each change without polling the source. A slot on the client's dev server would hold WAL whenever the machine is offline and, on a managed server shared by other applications, could stop all of them from writing ([why](notes/wal-slot-debezium.md#decision-1-no-slot-on-a-shared-database)). Real data, because months of real use is the strongest proof | 2026-10-18; revised 2026-10-22; stg added 2026-10-24; revised 2026-10-31 by the [2a spec](specs/data-path.md) (SeaweedFS, other OCR outputs out of 2a, the gold layer) |
| D6 | Training orchestration with **Argo Workflows**; **MLflow** for tracking and model registry (Postgres backend, artifacts in the lab's object store, SeaweedFS, chosen 2026-10-31). Each run picks its best epoch on validation; every candidate then faces one **promotion gate** on a frozen test split, split by document: the region detector by mAP@50 and recall against the production weights; a vision-language model, a prompt or a GPT deployment by top-1 and recall@3 on the human gold set against today's GPT, plus cost and p95 latency | The gate is what turns training into a safe lifecycle; validation alone is optimistic and answers a different question (which epoch is best, not whether the model is better than production) | 2026-10-18; revised 2026-10-22; **the orchestrator reopened for the 2b spec** (2026-11-11): Airflow, which many on-premise data platforms already run, is weighed there against Argo Workflows |
| D7 | Serving with **NVIDIA Triton** (ONNX and TensorRT). The **existing region detector is served first**, before any new training: `.pt` -> ONNX -> TensorRT FP32, FP16 and INT8 (calibrated on real page renders), compared on mAP@50 and recall on the frozen test split and on latency, against today's CPU; the self-hosted vision-language model is served by vLLM ([D20](#decisions)) | The worker becomes a thin client of the model server; serving does not wait for training | 2026-10-18; revised 2026-10-22 |
| D8 | Observability with **Prometheus, Grafana, DCGM exporter, OpenTelemetry**; golden signals with real baselines; alerts derived from the workload's real incidents (queue backlog and age, lock wait, consumer lag, refresh longer than its interval, schedule drift, stuck OCR files, container vs app memory limit), each proven by a replayed drill | Turns past incident lessons into platform controls | 2026-10-18; revised 2026-10-22; revised 2026-11-08: the alerts derived from the client's incidents are built on its live system, outside this lab; phase 3c observes model serving and adds the platform's SLOs |
| D9 | **GitHub Actions** CI: lint, tests, image build, **Trivy** scan, eval gate. Security baseline: non-root images, NetworkPolicy, Sealed Secrets | A change is linted, tested and scanned before Argo CD deploys it; where the eval gate runs is settled with O3 | 2026-10-18 |
| D10 | **No GitHub token on the machine; SSH keys per purpose**, each private key generated where it is used: laptop -> machine login (key in the gitignored `.scratch_ssh/`, installed with `ssh-copy-id`); machine -> GitHub (a **read-only deploy key** generated on the machine, created only when a phase first runs git on the machine: phase 1 needs none; I write and push from the laptop only); Argo CD -> GitHub (its own **read-only deploy key**, stored as a cluster Secret, [the handoff](notes/ansible-and-argo-cd.md#the-handoff)). The GitHub token stays on the laptop, held by `gh` | Nothing secret is transferred; each key covers one repo and one consumer and is revoked alone | 2026-10-18; revised 2026-10-19; the machine's own key at first use 2026-10-27 |
| D11 | Scope: a **core** of the phases on the [roadmap](../README.md#the-roadmap): the data path (2a, built), the training platform (2b), model serving with Triton, vLLM and the gateway (3a), retrieval with pgvector (3b), observability and day 2 (3c); then **extended** work: KEDA on Kafka, the student ranker and active learning ([D14](#decisions) B). The whole platform is designed first, in a concept design published before the build; each phase is published when its checks pass | A reader sees at once what the platform is and where it is going, every part marked built or planned | 2026-10-18; revised 2026-11-11: generative AI moved into the core ([D20](#decisions)), the student deferred, the concept design published first |
| D12 | Working method from my earlier lab: spec first, spec and code never duplicate, a question is a doc bug, one session per phase, isolated login config per tool ([AGENTS.md](../AGENTS.md), [how I work](how-i-work.md)) | Keeps the repo a reliable knowledge inventory | 2026-10-18 |
| D13 | **Passwordless sudo for my user on the machine during the lab**: set 2026-10-23 via `/etc/sudoers.d/<user>` and verified; removed by the teardown playbook when the lab ends | I do not type a sudo password at each run. Anyone holding the SSH key has root on a machine the AI team also uses, so it is kept to the lab days and removed at teardown ([the inventory](specs/gpu-box-platform.md#teardown)) | 2026-10-19 |
| D14 | The lab trains **both models of the two-step system** ([workload](#the-workload)): (A) the one-class **region detector**, from the AI team's human-labelled boxes (the labelled pages: 2,041 pages from 132 garment specs, 3,493 boxes), retrained reproducibly in Argo; (B) an **open-vocabulary student ranker** that reads the element prompt, distilled from GPT's rerank scores (about 62,600 GPT-scored pairs in dev and stg) and judged on human picks (250 with a crop on 2026-10-31: dev 130, stg 120; the 200 that join to their model output are the gold set; they come from 27 curated results, 15 of them last saved by my team and 12 by the client's staff), grown by active learning from the elements the model itself marks for `review` (4,870 in dev, 2,061 in stg); production shape: a cascade where GPT sees only what the student is unsure of | Fits the real data: humans draw boxes in the AI team's labelling tool and pick crops in Odoo, but never correct boxes in Odoo. The product moves from fixed classes to custom prompts (64 of 100 elements custom in dev), so a prompt-reading student can replace per-element GPT calls. Covers auto-labelling, active learning, dataset quality and training infrastructure | 2026-10-22; **(B) deferred to the extended work** (2026-11-11): training a new model is the ML engineers' work, not the platform's; the platform gives the AI team training, gates and serving for (A), and T3 is pursued by serving a self-hosted vision-language model instead ([D20](#decisions)) |
| D15 | **Lineage and one gate for every change**: each output records the weights hash, registry version, prompt hash and GPT deployment; a new detector, vision-language model, prompt or GPT deployment runs the same evaluation (accuracy, cost, latency) before use. Core: lineage and the shared gate on the garment-spec gold sets. Extended: a second OCR flow of the client's, in development only (2,279 records with OCR values next to the final ones) and the AI team's reference pairs of an original PDF and its standard document. The lab calls the dev GPT deployments in Microsoft Foundry only for evaluation, never to make training labels; how it authenticates is decided in that phase's spec | The gaps today: weights versioned by file name only, GPT deployments switched by configuration, prompt evaluations run by hand ([use case](use-case.md#where-it-falls-short-today)) | 2026-10-22 |
| D16 | **The client's real data only, measured against the existing system.** Every outcome (T1 to T9) starts from a real baseline of today's system (the production weights, GPT's scores and cost, the human picks, the incidents) and reports how far the lab moves it. The public repo shows the lab's record without its data | I chose real data because the mess is the point of MLOps | 2026-10-22 |
| D17 | **The client's code is never copied into the repo.** The lab reads the OCR service's code to understand it, and the client's **data** (databases, Blob) to learn from it, but builds its own code. Allowed: read-only clones outside the repo, push disabled; quoting a file and line in a doc. Not allowed: copying a file or function of the service into `pipelines/` or `services/`; committing its packages. One exception: if a phase must reproduce a step of the service exactly (for example cutting crops with the service's own geometry so they match production pixel for pixel), it installs the package into a gitignored environment on the machine, never into git | Git keeps every commit forever, so code committed once stays in the history; built by the AI team for the client, it is the client's property and must never reach the public export. The lab needs the service's **outputs** (runs, scores, picks), not its code | 2026-10-23; confirmed 2026-10-24 |
| D18 | **An AWS track next to the machine (2026-11-03):** the same platform as Terraform for AWS (VPC, IAM, S3, RDS, EKS, Karpenter) and a per-cluster overlay of the Argo CD apps, run on kind and LocalStack with no AWS account, plus the operations drills: autoscaling, a spot reclaim, a database upgrade and point-in-time restore, an alert that finds a fault, canary releases, cost and Git flow ([spec](specs/aws-track.md)) | A cloud-agnostic check of the platform's design: the GPU machine stays the GPU platform, the track shows the same design on AWS. Nothing is claimed as applied to AWS: what ran on the emulator, the mock or kind says so | Built 2026-11-04 |
| D20 | **Generative AI in the core (2026-11-11):** a small open **vision-language model served by vLLM** on one RTX 3060; one **OpenAI-compatible gateway** in front of the GPT deployments in Microsoft Foundry and vLLM, so the team switches models by configuration, with usage and cost per key and the answering model recorded; **pgvector** on the lab's existing CloudNativePG Postgres, holding crop and element embeddings so the nearest human-picked crops can be retrieved as context (RAG on the OCR's own data). Agents are studied, not built. The model, its quantisation and the gateway are chosen in the 3a spec | ML platforms now serve LLMs beside classic models, with retrieval and vector search. The real problems behind it: every element goes to GPT (P5), past picks are never reused (P8), models change by configuration with no record (P3). pgvector reuses a Postgres the lab already runs instead of adding a store | 2026-11-11 |

D19 is a decision about work outside this lab; it stays in the lab's private repo.

## If the lab used a public dataset

Weighed on 2026-10-22, before D16 settled on real data, and kept as the comparison that settled it; this public repo
uses no stand-in. Checked 2026-10-22: **no public dataset has garment-spec pages with region boxes and element
labels.** The closest stand-ins, each for one step only:

| Step | Stand-in | Gap |
|---|---|---|
| A. Find regions | DocLayNet: 80,863 document pages in 6 categories (financial reports, manuals, patents, laws, tenders, science), 11 layout classes incl. Picture and Table ([GitHub](https://github.com/DS4SD/DocLayNet), read 2026-10-22 through a summarising tool); licence: [V8](#to-verify) | Office documents, not garment drawings |
| B. Assign regions to elements | Fashionpedia: 46,781 photos with garments and garment parts (collar, sleeve, button...) ([paper](https://arxiv.org/abs/2004.12276)), or the flat-sketch dataset of HiGarment ([paper](https://arxiv.org/abs/2505.23186), ICCV 2025); licences: [V8](#to-verify) | Photos or sketches, not garment-spec pages; no element prompts, no GPT teacher scores, no human picks |

| Part of the lab | With the client's real data | With a public stand-in |
|---|---|---|
| Platform: k3s and GPU, Argo, MLflow, Kafka, Debezium, Spark, Iceberg, Triton and TensorRT, gates, lineage, CI, observability | Built | **Unchanged** (data-agnostic) |
| Detector track | Real production weights and the AI team's labels ([V9](#to-verify)) | Retrain on DocLayNet; no production baseline (the client's weights are derived from customer data) |
| Student track | About 62,600 GPT-scored pairs already paid for, 250 human picks, real prompts | Invent element prompts; pay a teacher (GPT or an open VLM) to label; no real human picks |
| Data path | Real runs and edits replayed (D5) | Synthetic events |
| Alerts | From real incidents on this workload | Same designs, no live baselines |
| Story | "Took a real two-model system and gave it training, gates and lineage" | "Built an MLOps platform on public data" |

So a public dataset keeps the platform but **loses the use case**: the real teacher scores, the human picks, the
production baseline and the cost story. So the lab uses real data, and the public repo shows its record (code,
runbooks with real output, acceptance results) without the data, with no stand-in ([D2](#decisions),
[D16](#decisions)).

## The workload

The full picture is the [use case](use-case.md). What matters for the design:

- The OCR service, built by the AI team and used daily in the client's staging environment, is called by the client's Odoo through Service Bus queues, with results pulled
  over HTTP.
- **GPT vision does the element matching**, fed by Document Intelligence's text: it reads each page against all
  elements, scores the YOLO crops on the pages that need them, then ranks each element's candidates side by side
  ([the flow](use-case.md#the-flow)). The only self-hosted model is a **one-class YOLO** that finds "regions the
  template needs", run only on those pages, on CPU, trained by the AI team on Ultralytics Platform from 2,041
  human-labelled pages of 132 garment specs; its validation leaks (99 of 146 validation pages share a garment spec
  with training).
- **Humans do not correct boxes.** In the editor they pick, swap, drag in or remove candidate crops per template slot,
  and each slot carries element ids. The labels are "this crop is element X" (positives) and "not this one"
  (removals), not box geometry. They fit a crop-to-element classifier or ranker; detector boxes come from the AI
  team's own labels instead ([D14](#decisions)).
- No automated evaluation against human choices, in the service or in Odoo (the AI team's checks against reference
  pairs run by hand), and no registry, retraining, metrics or tracing. The MLOps gap behind D1 holds.
- Getting labels out is real data engineering: one JSON per result, its slots as plain JSON and again inside a binary Yjs snapshot
  (a shared-editing document format; the plain copy is enough, V6), full-copy
  history capped at 300 versions, and no detection id per slot (join by run id, page and box match).

## Data sources (verified 2026-10-19)

What the lab reads and what each source is for. Where each one lives: [the use case](use-case.md#where-each-piece-lives).

| Data | Role in the lab |
|---|---|
| Garment-spec PDFs | Raw input |
| Page renders | The images the models see |
| Model output per run (units, candidates and scores, chosen crop per element) | Predictions (the "before") and the GPT baseline |
| Human choices (curated results and their history in Odoo) | Labels (the "after") |
| The production region detector's weights | The production baseline every new detector is gated against ([D6](#decisions), [D7](#decisions)) and the first model served on Triton |
| The AI team's labelled pages | Detector training and the test set split by document (T1, T2) |
| Templates | The expected elements per document kind, read at slot level ([V10](#to-verify)) |
| Reference pairs (an original and its standard document) | End-to-end check ([D15](#decisions) extended) |
| The second OCR flow (development only) | OCR values next to the final ones ([D15](#decisions) extended) |

## Open decisions

| ID | Question | Needed before |
|---|---|---|
| O2 | Image registry: GitHub's (private) pulled by the machine, or a registry inside the cluster | The first phase that builds its own image (phases 1 and 2a used only public images) |
| O3 | GitHub-hosted CI runners cannot reach the machine on the private network. Argo CD pulls from GitHub, so CD works; confirm CI only needs to push images | Phase 2b |

## To verify

Nothing is open. What was checked before the decisions above relied on it:

| ID | What | Result |
|---|---|---|
| V1 | The OCR pipeline's facts, read in the service's code | 2026-10-19: several earlier assumptions did not hold; the [use case](use-case.md) describes the service as read |
| V2 | Shape of the correction history in Odoo | 2026-10-19: one JSON per result with its full history; volumes in V5 |
| V3 | The rest of the GPU machine | 2026-10-25: 28 threads, 31 GiB RAM (13 available, 10 GiB swap in use), **root disk 98% full** (9 GB free; 467 GB free on `/mnt/data`), both GPUs used by the AI team, container toolkit 1.20.1 and Docker's `nvidia` runtime installed; every registry, GitHub, HuggingFace, PyPI and Ultralytics reached ([platform spec](specs/gpu-box-platform.md#decisions)) |
| V5 | Real usage, and permission to use the data | 2026-10-22: stg is the environment the staff work in; use of the client's real data in the private lab confirmed; it stays on the laptop and the machine, outside Git, and is never exported |
| V6 | A human-chosen slot joins back to its service unit, and Python reads the slot's element ids | 2026-10-31: a result keeps its slots as plain JSON beside the Yjs snapshot (they agree on 457 of 461 pages), so results need no decoder; every crop whose page image survives (200 of 250) matches a unit of its run at IoU 0.9 or more, once both service databases are searched (dev's results name stg runs); 50 lost their page image |
| V11 | Whether each `result_history` version carries its own time | 2026-11-01: yes, each entry has a `create_date` (2,585 entries in the results' and templates' histories, dev and stg, none without); the replay writes each version at that time ([2a spec](specs/data-path.md#replay)) |
| V7 | Where the YOLO training data, labelling tool and training live, and the class list | 2026-10-21: Ultralytics Platform, **one class** |
| V8 | Licences of the public stand-in datasets | 2026-10-22: DocLayNet is CDLA-Permissive-1.0 (use, adapt, publish; keep credits, ship or link the licence, mark changed data; analysis results are free of conditions, [LICENSE](https://github.com/DS4SD/DocLayNet/blob/main/LICENSE)); Fashionpedia annotations are CC BY 4.0 while its images keep their sources' terms ([terms](https://fashionpedia.github.io/home/data_license.html)); the HiGarment flat sketches need an application form. All read 2026-10-22 through a summarising tool. Not used: the lab uses real data (D16) |
| V9 | The labelled pages' structure | 2026-10-23: 132 garment specs, split by page with 99 of 146 validation pages leaking from training documents, 51 background pages; it is the production training set |
| V10 | Read a template's slots from the per-page Yjs snapshots | 2026-10-31: `pycrdt` (a Python reader for Yjs) decodes every template page (dev 917, stg 1,548); a slot names one element or none |
