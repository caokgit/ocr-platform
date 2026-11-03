# docs/

Every page in `docs/`, here or in its folder's index, grouped by what it is for. New here? Start with the [README](../README.md); come back
here to find a page.

## The use case, and how the work is done

| Page | What it holds |
|---|---|
| [use-case.md](use-case.md) | The workload on one page: who is involved, one garment spec through the system, what "correct" means, where it falls short |
| [how-i-work.md](how-i-work.md) | How I work with an AI coding agent: the method, and three errors it caught |

## The lab: what it decides

| Page | What it holds |
|---|---|
| [design.md](design.md) | Context, target outcomes, decisions (D#), open decisions, what was verified |
| [specs/gpu-box-platform.md](specs/gpu-box-platform.md) | Spec, phase 1: k3s, the GPU Operator and Argo CD on the shared machine next to the AI team's Docker; lab-up, lab-down, teardown, acceptance A1 to A11 |
| [specs/data-path.md](specs/data-path.md) | Spec, phase 2a: snapshot, replay, CDC, Kafka, Iceberg on SeaweedFS, gold sets; acceptance B1 to B16 |
| [specs/aws-track.md](specs/aws-track.md) | Spec, the AWS track: Terraform for AWS (LocalStack and a mocked apply), the kind and EKS overlays, the operations drills; acceptance C1 to C20 |
| [aws-cost-estimate.md](aws-cost-estimate.md) | What the AWS track's dev design costs a month, from AWS's public price list, by scenario |
| [specs/dataset-intake.md](specs/dataset-intake.md) | Spec: how the detector dataset enters the lab, its output and acceptance checks |
| [known-failure-modes.md](known-failure-modes.md) | Real failure modes met in the lab: symptom, cause, fix, recovery |

## Doing it

| Page | What it holds |
|---|---|
| [runbooks/](runbooks/README.md) | How to do each operation **now**: complete, tested flows with commands, their real output, checks and rollback |

The lab also keeps a journal, one entry per session with the commands run and the incidents as they happened; it is
not published ([the rule](../AGENTS.md#living-docs-and-the-journal-never-mixed-owner-2026-10-25)).

## Phase reviews

The story of each phase, written at its end: what it built, why each tool, what it taught, what the next phase
inherits. Each links to the spec, runbooks and design notes that hold the facts.

| Page | What it holds |
|---|---|
| [phases/phase-1-gpu-box.md](phases/phase-1-gpu-box.md) | Phase 1: k3s, the GPU Operator and Argo CD on the shared machine |
| [phases/phase-2a-data-path.md](phases/phase-2a-data-path.md) | Phase 2a: the client's OCR tables copied once, replayed through Debezium and Kafka into Iceberg, and cut into the gold sets |
| [phases/aws-track.md](phases/aws-track.md) | The AWS track: the platform written for AWS and EKS, proven by a mocked apply, LocalStack, kind and measured drills |

## Design notes

| Page | What it holds |
|---|---|
| [notes/](notes/README.md) | Nine engineering questions the lab settled, each with its real values |

## Keeping this index complete

Every Markdown page under `docs/` is listed here, except the pages of the folders that keep their own index: the
runbooks in the [runbooks index](runbooks/README.md), the design notes in the [notes index](notes/README.md).
`python3 tools/check-docs.py` fails when a page is missing from its index (this page, or its folder's), so a new page is added to its index in the
same commit that creates it.
