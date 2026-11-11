# AGENTS.md

Rules for any coding agent (Claude Code, Codex, ...) working in this lab. This public repo is exported from the lab's
private repo, where the agent works: these are the rules it follows there, every rule with its date, in public names.
Claude Code reads this file natively (its memory docs, checked 2026-10-18). **Never add a `CLAUDE.md` or `CLAUDE.local.md`**, to this repo or to any folder above it: if either exists, Claude
Code stops reading this file by default.

The lab is the owner's **knowledge inventory**: an MLOps platform for a garment-spec OCR workload (see
[docs/design.md](docs/design.md)). Every fact found along the way (machine probes, service facts, measurements,
sources) is written down in the matching doc, never only in chat.

Some pages these rules name stay in the private repo: the journal, the status page, the learn pages, the lab's
machine facts and the publishing spec. They are named here without links; the [table at the end](#what-goes-where)
says which pages are published.

## Rule 0: spec first

Nothing is implemented before its spec section exists in `docs/`. A commit that touches an
implementation path (`infra/`, `pipelines/`, `services/`, `tools/`) carries a trailer
`Spec: docs/<file>.md#<anchor>`. `tools/hooks/commit-msg` rejects the commit when the trailer, the
file or the anchor is missing. Docs-only commits need no trailer.

When writing the code shows that an approved spec is wrong or incomplete (a limit of the platform, a case it did not
cover), fix the spec first, in a docs commit of its own, then write the code; list each change for the owner at the
next stop, so an approval never covers a design that silently moved (2026-11-08: a platform limit turned one alert
with two severities into two rules).

## Spec and code never duplicate each other

- **The spec owns** design, decisions (with the why), contracts between components, and acceptance
  criteria.
- **The code owns** how things are implemented and behave: config values, flags, schemas, versions,
  commands.
- A doc **links to the file** instead of restating what the file says. A doc that restates code is a
  doc bug: replace the copy with a link.
- When code and spec disagree on behaviour, the code is the truth about *what happens*; fix the spec
  if the design changed, or fix the code if it drifted from the design.

## A clarification question is a doc bug

Whenever the owner asks about a concept or about something built, however small: answer in chat
**and** in the same turn add or extend a section in the matching `docs/learn/<topic>.md` (the lab's study pages, not
published; the [design notes](docs/notes/README.md) are drawn from them), add a row to the learn pages' question
finder, then commit. A learn section:

- opens with `Asked on <YYYY-MM-DD>: "<the question>"`,
- teaches, decides nothing, and ends with `**In our design:**` pointing to decision IDs (D#),
- labels examples **REAL** (captured here, dated), **DOCS** (from vendor docs), **PLANNED**, or
  **TOY** (invented numbers that only show the arithmetic),
- uses a Mermaid diagram when a flow is involved; a colour SVG diagram in `docs/learn/diagrams/` is welcome to connect components and
  flows on one picture, rendered and checked before commit (owner, 2026-10-29),
- explains the concept **and its purpose** (why it exists, what it is for here), then demonstrates it
  with **real values from this lab** (a dev record, a measured number, a real config value) and a
  diagram or figure (a text diagram renders everywhere); invented values are marked
  **ILLUSTRATIVE** and used only when no real one exists (owner, 2026-10-21).

Every new tool gets a learn page **before** its spec section. An answer covers the whole set the question points at,
not only the example named (owner, 2026-11-07: "apart from 502, are there other codes?").

Real values from this lab come first in every example (owner, 2026-10-21, confirmed 2026-10-30): a value
seen here teaches more than a made-up one.

Videos suggested for a topic go into the learn pages' "Videos to watch" list, in watching order, with what each
prepares for and a "Watched" column the owner updates (owner, 2026-10-28).

The owner asks ad-hoc questions in other sessions too, so `docs/learn/` grows from several places.
Before adding a section, read the question finder and the pages it touches:
extend or link instead of repeating, merge overlaps, and fix any fact a later finding made stale.
Reorganising pages for a better learning path is welcome (owner, 2026-10-22).

## Sources sit next to the content

Every external fact, and every paper or doc used to explain a concept, carries its source link and
access date in the same paragraph or table row, so the owner can go back to it to study:
`... ([source](https://...), 2026-10-18)`. No separate reference lists. If a source was read through
a summarising tool, say so and copy exact quotes from the live page before quoting. Prices come from a price list or
an API that shows the numbers (a cloud's pricing page can show none to a fetch; its price API does).

## Sessions and logins

- **One Claude Code session per phase** (a build step or an experiment run). The new session
  replaces the old one. Start from the repo, not from memory: read this file, the status page,
  `git log --oneline -15`, `git status`.
- End a phase with docs updated, the session's journal entry closed, checks green, a commit, and the next session's
  setup rewritten in the status page: the mode to start in, where the owner must be, and the prompt to paste. Journal
  times come from `date +%H:%M` run in the same command that writes the row, never estimated.
- **A phase ends with its review** (owner, 2026-10-31: a careful review after each phase strengthens the
  lab's content and the owner's knowledge; checking it against its sources finds errors the other pages
  hide): `docs/phases/<phase>.md`, the phase's story in one
  read, listed in [docs/README.md](docs/README.md#phase-reviews). It links to the spec, runbooks, journal
  and learn pages that hold the facts and never copies them. Its outline, the same for every phase: the
  phase in one picture (a diagram and its one idea); what it delivered, with evidence; what runs and who
  installed it; who does what (the tools); the decisions that shaped it; what we learned; what the next
  phase inherits; catch up in order. The model: [phase 1](docs/phases/phase-1-gpu-box.md).
- **Stop the lab before a session ends** (owner, 2026-10-30): if k3s is running on the GPU box, the agent
  proposes `lab-down` before it stops ([lab session](docs/runbooks/lab-session.md)); between sessions the
  box is the AI team's alone.

### Which mode a session runs in (owner, 2026-10-25)

Claude Code's permission mode is chosen by the owner when the session starts, and switched during it as
the work changes. The rule, by kind of work:

| Work | Mode | Why |
|---|---|---|
| Reading, docs, learn pages, read-only probes of the box or the client's cloud | **Auto** | Writes stay in the repo; the safety check still stops a risky command ([classifier block](#safety-and-approvals)) |
| A live change outside the repo: the box, cloud resources, GitHub settings | **Manual** | Every command waits for the owner, on top of the rule to show each change first |
| Choosing between designs before a spec exists | Normal work, the spec shown for approval; **Plan mode** only when the owner asks or several options must be weighed first | Plan mode can write only its plan file, so it blocks journal, learn and probe writes; the spec in `docs/` is the plan that lasts. Plan revisions are kept as in [Plans](#plans) |

- A session never starts in Plan mode by default.
- When the work moves to the next row, the agent says so **before** the first command of that row (for
  example "the next step changes the box: switch to Manual"), and waits.
- A command blocked in Auto mode follows the [classifier block](#safety-and-approvals) rule.
- **Every tool login gets its own gitignored config folder**, re-exported on each command:

  | Tool | Isolation |
  |---|---|
  | gh | `GH_CONFIG_DIR=$PWD/.scratch_gh` |
  | kubectl, helm | `KUBECONFIG=$PWD/.scratch_kube/config`; helm also `HELM_CACHE_HOME=$PWD/.scratch_helm/cache HELM_CONFIG_HOME=$PWD/.scratch_helm/config HELM_DATA_HOME=$PWD/.scratch_helm/data` (else it writes `~/.cache/helm`) |
  | az | `AZURE_CONFIG_DIR=$PWD/.scratch_az` |
  | HuggingFace | `HF_HOME=$PWD/.scratch_hf` |
  | psql (the client's dev and stg Postgres) | `PGSERVICEFILE=$PWD/.scratch_pg/pg_service.conf PGPASSFILE=$PWD/.scratch_pg/pgpass`, then `psql service=<name>` |
  | Ultralytics (every run of the package; the key only if asked for one) | `YOLO_CONFIG_DIR=$PWD/.scratch_ultralytics ULTRALYTICS_API_KEY="$(tr -d ' \r\n' < .scratch_ultralytics/api_key)"`; the settings folder variable is named in Ultralytics' own warning message ([log](https://huggingface.co/spaces/Docfile/Yv), [settings](https://docs.ultralytics.com/usage/settings), 2026-10-23); confirmed 2026-10-25: settings land in `.scratch_ultralytics/Ultralytics/settings.json`, where `sync` (usage analytics) is set to `False`. Without the variable, the package writes `~/.config/Ultralytics/` ([known failure modes](docs/known-failure-modes.md)) |
  | Ansible | `ANSIBLE_CONFIG=$PWD/infra/ansible/ansible.cfg ANSIBLE_HOME=$PWD/.scratch_ansible`, run as `.venv/bin/ansible-playbook` ([laptop setup](docs/runbooks/laptop-setup.md#6-ansible-in-venv)) |
  | ssh (laptop to GPU box) | `ssh -F $PWD/.scratch_ssh/config gpu-box` (key, known_hosts and address all in `.scratch_ssh/`) |

  Credential files are mode 600.

## Plans

Every revision of a session plan is saved as a numbered plan file, never overwritten; the plans are tracked in the
lab's private repo and never published, so a plan holds no secret (credentials live in a gitignored folder of their
own). Plan mode can write only its own plan file, so when a plan is revised in plan mode, save the previous revision
the moment plan mode exits, and tell the owner. Decisions that survive go into [docs/design.md](docs/design.md).

## Safety and approvals

- **Network reach** (owner, confirmed 2026-10-31): **at home, the office VPN is needed for the GPU box; at the office, it
  is not.** The client's systems have their own access rule, in the lab's private data access runbook. Before any
  access, ask where the owner is and, from home, to turn the VPN on.
- **GPU box:** before each step on the box, show the change (`--check --diff` for a playbook), name the
  runbook section it will land in, and wait for the owner's go (owner, 2026-10-30). Box facts go to the lab's
  machine page with credentials and the hostname left out.
- **Classifier block:** if a command is blocked by the auto-mode safety check, stop, say what was
  blocked and why it is needed, and ask the owner to switch to Manual mode. After they confirm, run
  the **same** command again. Never reshape a command to get past the check. Long scripts go in a
  scratch file run as `bash <file>`, not `bash -c`.
- **Secrets** never appear in a file, commit, log or chat, not even a prefix. Name a secret by its
  path or key only. Credentials live in gitignored files. Inspect credential files by names and shapes; read private
  notes by their headings and never print a section that holds credentials (a mask that catches only labelled values
  misses a password alone on its line, 2026-11-07).
- **Live changes outside the repo** (cloud resources, the box, GitHub settings) are shown first as their dry run
  (`--check --diff` for a playbook, `terraform plan`, the SQL about to run), with the runbook section they will land
  in, and run only after the owner says go. A change to a shared system goes to its rehearsal copy first (development
  before staging, the lab before the box) (2026-11-08).
- **Cleaning something live:** edit the value in place first and delete only after, because a soft-deleted copy (a
  storage account, a key vault) keeps what it had when deleted; and before saying a value is gone, check every place
  it was written (the resource, its role assignments, state files, image manifests, logs, the activity log), not
  only the resource. An audit log that cannot be edited is recorded, not fought (2026-11-08).
- **Wrappers fail closed:** a script that wraps a live change (plan then apply, build then push) stops at the first
  failed step and leaves nothing behind for the next step to act on: a failed plan deletes its plan file, and apply
  refuses without a fresh one (2026-11-08: a failed plan left the previous one, which apply then applied). Show each
  plan, then apply it in a separate step, never chained.

## Git

- Concise commit subjects in plain English; prefix `docs:` for docs-only commits.
- **No `Co-Authored-By` or other AI attribution lines** (the hook rejects them).
- Never `--no-verify`. Push without asking only when it is a fast-forward of `main`.
- **The VPN at home and the internet** (owner, 2026-10-30): with the VPN on, GitHub and most web fetches
  failed or hung from WSL until 2026-10-30; on 2026-11-07 pushes and fetches worked with it on. If one hangs,
  the agent commits locally, keeps working, and tells the owner when the VPN must go off: to push, or to search and
  read sources on the web, instead of failing quietly or working around it. From the office, or at home with the VPN off, it pushes as it goes.
- The lab's repo stays **private**. This public showcase is a separate repo with fresh history, exported
  from allowlisted paths and checked against the lab's publishing spec first. The public repo is pushed by the owner only.

## Private vs public

The lab's repo may freely use internal terms, my team's and the client's names. None of that goes public: the
export renames or removes it, and a search gate checks for it. **When a new internal or strategic term enters the
lab's repo, it is added to the publishing spec in the same commit.**

## Writing

- No em dashes (`tools/check-docs.py` rejects them). Short sentences, tables for comparisons.
- **Mask little, keep values real** (owner, 2026-10-30): realistic values help comprehension, so internal
  (private) addresses, versions, ports, ranges, counts, public keys and their fingerprints are written as
  they are (the lab's repo is private; the public export masks internal addresses).
  Never written: hostnames, passwords, tokens, public addresses of the owner's or the office's connections,
  and other people's names. Output that can hold any of these goes through [tools/mask.py](tools/mask.py).
- What the docs never write stays out of committed code too: a read-only discovery script finds each resource by its
  role and writes the names into gitignored files that the code and the tools read; the same script writes the mask
  words (2026-11-08).
- Folder structure is not frozen: improve it when it stops fitting. Move with `git mv`, rewrite every
  link, run `python3 tools/check-docs.py`, never leave a stub.

### How a doc reads (owner, 2026-10-24)

Docs are revised often, so every revision keeps them clear, not only correct:

- **Ordered.** A page opens with what it is for and where it fits (one or two lines, links to its
  neighbours). Then the overview, then the detail: what, why, how, examples. One topic per section;
  headings a reader can scan.
- **Demonstrated.** Every concept or claim comes with a concrete example, real values from this lab
  first, then a table for comparisons and a diagram for flows.
- **Connected.** Link the page that holds a fact instead of repeating it; link back from where the
  reader would look for it (the question finder, the use case, design).
- **Current, never appended.** Revise the section a new fact changes, do not add a paragraph below the
  old one: rewrite the sentence, update the number and its date, delete what is superseded (git keeps
  the history). When a fact changes, search the docs for its old value and fix every copy. Measured
  numbers carry their date; data that keeps changing says so.
- **Re-read before committing.** Read the whole section as a newcomer would: does it flow, does each
  step lead to the next, is anything stale or said twice?
- **Explained by following one thing (owner, 2026-10-25).** An explanation opens with the **one idea**
  that explains everything, in one bold sentence. Then it follows one concrete thing (a packet, a record,
  a request, a command) through each case in order: what fails first, then each change and what it
  fixes and what it does not. One small diagram per case, plain words before terms (each term defined in
  a short clause where it first appears), what was measured kept apart from what cannot be seen, and a
  side-by-side table of all cases at the end. The model, in its public form:
  [reaching a lab machine through a full-tunnel VPN](docs/notes/wsl-and-a-full-tunnel-vpn.md).
- **One story per page, not a pile of answers (owner, 2026-10-27).** Content may be rich, but every part
  connects: a page is not a set of independent knowledge puzzles. Pages grow one question at a time, so
  every time a section is added, re-read the **whole page** and fix its flow: open with a map (a diagram or
  table of the pieces and how they connect), order the sections so each builds on the one before, say in
  each section how it links back to the map, merge facts said twice, and move background to the end. A
  question's `Asked on` line stays with the section that answers it, even when sections are merged. The model: the
  lab's Python packaging page (one map, then a before-and-after story).

### Living docs and the journal: never mixed (owner, 2026-10-25)

The lab keeps a track record of every step and every incident, **and** docs that read as one complete,
current flow. Those are two kinds of page, and an event never goes into a living doc:

| | Living docs | Journal (private, not published) |
|---|---|---|
| Answers | How things are, and how to do them, **now** | What happened, **when**, in what order |
| Pages | `design`, `use-case`, `lab/`, `learn/`, [runbooks/](docs/runbooks/README.md), [known-failure-modes](docs/known-failure-modes.md) | `journal/YYYY-MM-DD-<slug>.md`, one per session |
| Changes | Revised in place ([how a doc reads](#how-a-doc-reads-owner-2026-10-24)) | Written during its session; **frozen** after the session's last commit (only broken links are fixed) |
| Commands | The current, tested way: copy-pasteable, with the expected output and a check | What was actually run, with the real output trimmed, **failed attempts included** |
| Incidents | `known-failure-modes`: one row per failure mode, updated when it recurs | The incident as it happened: timeline, impact, how it was found, the fix, a link to the row |

- **Every step** done in a session is in its journal entry, with the command and its real output. Every
  step meant to be repeated ends up in a **runbook**, rewritten until it is the complete flow from
  prerequisites to verification and rollback. The journal links to the runbook section; a runbook never
  says "on 2026-10-25 we ran".
- **Every incident** (something broke, a wrong assumption cost time, a secret showed in output, a command
  was blocked) gets a journal section `Incident: <what>` and a `known-failure-modes` row, new or updated,
  that links to it.
- **An incident in the system a repo watches or runs** (users felt it, or a second team was needed) gets a
  **blameless post-mortem**: impact, a timeline with a source per line, contributing causes in the system (never a
  person, and nobody named), what the monitoring saw, action items with an owner and a state. It is a record like
  the journal: frozen once reviewed, except its action items' states (2026-11-08: two real ones showed that writing
  them from the raw data also corrects earlier write-ups).
- **Runbooks call the code, they never copy it** ([spec and code](#spec-and-code-never-duplicate-each-other)):
  an automated step is one command naming its file (`ansible-playbook infra/...`); the runbook adds what
  code cannot hold: the order, prerequisites, how to check, how to roll back.
- **Runbooks cover the whole journey (owner, 2026-10-30).** [runbooks/README.md](docs/runbooks/README.md) is
  the map, from a fresh laptop to a running lab and back to a clean box; pages are cut by how often they
  run (once per laptop, once per box, every session, at the end). Each page:
  - is **read and revised as a whole**, concise and easy to follow, one complete flow, never a set of
    independent pieces;
  - shows every command **followed by its real output** (dated, trimmed, masked) and a `Check:` line;
  - weaves each incident met into the step where it happens, as an "If you see ..." line linked to its
    `known-failure-modes` row, written for the reader who follows the steps, not as an event log;
  - is **written in the same step as the execution**: a command run on the box lands in its runbook
    section, with its output, before the next step starts, not after the phase.
  Every stage on the map gets its page, written as that stage first runs, so the whole journey is captured.
- **Teardown grows with the lab** (owner, 2026-10-30): teardown is scoped to the GPU box, so the box is as
  if the lab never existed. Whatever the lab adds to the box, or grants for the box's sake (a file, a rule,
  a module, a key such as Argo CD's deploy key), gets its removal in the same commit that adds it: a row in
  [the spec's teardown inventory](docs/specs/gpu-box-platform.md#teardown) and a step in `teardown.yml`.
  `footprint.yml` reruns before the real teardown to catch what was missed; the scan's limits are written
  in the spec. The laptop's own setup is not teardown's: each stage's runbook has its roll back.
- **Plan mode with the owner whenever a choice needs planning** (owner, 2026-10-30): reorganising the docs
  (moving procedures, changing the runbook set), or several ways of doing a step; the agent proposes
  entering it, before the work starts.
- **Both read well.** A journal entry opens with a summary (goal, outcome, what changed in which doc), so
  nobody has to read the timeline to know the result; then a timeline table, the commands, and a diagram
  or a measured table wherever one explains faster than prose. The templates (journal entry, runbook page,
  learn section, review, post-mortem) stay in the lab's private repo.
- Commands and outputs in both follow [safety](#safety-and-approvals) and [writing](#writing): secrets named
  by path only; internal addresses kept; the hostname, public addresses and other people's names hidden.

## What goes where

| Path | Holds | In this repo |
|---|---|---|
| [README.md](README.md) | The lab's overview; the public one has the problem statements, the outcomes, what is built and the roadmap | Yes, public only |
| [docs/README.md](docs/README.md) | The index of every page in `docs/` (the checker fails when one is missing) | Yes |
| [docs/use-case.md](docs/use-case.md) | The business use case: actors, inputs and outputs, the flow, what "correct" means, today's gaps | Yes, rewritten for the public |
| [docs/design.md](docs/design.md) | Context, the problem statements and outcomes, the decisions D# and the open decisions | Yes, rewritten for the public |
| `docs/public-export.md` | The publishing spec: how the public repo is produced from the lab, what never reaches it, the gates | No |
| `docs/learn/` | Concept pages, reading order, question finder | No; the design notes below are drawn from them |
| [docs/notes/](docs/notes/README.md) | Design notes: the engineering questions the lab settled, with real values | Yes, public only |
| [docs/how-i-work.md](docs/how-i-work.md) | How the owner works with the agent, and three errors the method caught | Yes, public only |
| `docs/status.md` | What is verified, and the next step | No |
| [docs/known-failure-modes.md](docs/known-failure-modes.md) | One row per real failure mode: symptom, cause, fix, recovery, links to the incidents | Yes, without the incident links |
| `docs/specs/` | One spec page per component: design, contract, acceptance; the anchors that `Spec:` trailers point to | Yes, rewritten for the public as each is built |
| [docs/runbooks/](docs/runbooks/README.md) | How to do each operation now: complete, tested flows with commands, checks and rollback (living) | Yes, in public names; the data access and publishing runbooks left out |
| `docs/journal/` | One entry per session: what was done, the commands run, incidents (event log, frozen after the session) | No |
| `docs/lab/` | Snapshot of what exists now (machines, clusters), facts only | No |
| `infra/` | Ansible playbooks, Helm values, Argo CD apps | Yes |
| `pipelines/`, `services/` | Data and training pipelines, serving and worker code | Yes |
| `tools/` | Repo checks and git hooks | Yes, without the export script |
| [docs/phases/](docs/README.md#phase-reviews) | One review per phase, written at its end: its story, linking to the facts | Yes, rewritten for the public |

## Checks

```bash
git config core.hooksPath tools/hooks   # once per clone
python3 tools/check-docs.py             # links, anchors, em dashes, secret/IP-shaped strings
```
