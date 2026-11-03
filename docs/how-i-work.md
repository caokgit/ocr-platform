# How I work

How this lab is built: with an AI coding agent, under rules that make its work checkable. The [README](../README.md)
says what the lab delivers; this page says how, and shows three errors the method caught before they shipped.

**The one idea: every step leaves evidence that someone else can check, and nothing is built before it is written
down. The design comes first as a spec, every external fact carries its source, a second reader checks the work
against those sources, and every repeatable step lands in a runbook with its real output.**

## The method

The rules live in [AGENTS.md](../AGENTS.md), which the agent reads at the start of every session. A
[commit hook](../tools/hooks/commit-msg) enforces two of them, and [a docs checker](../tools/check-docs.py), run
before each commit, catches broken links and anchors, em dashes and secret-shaped strings.

| Practice | What it means | How it is enforced or shown |
|---|---|---|
| Spec before code | A component's design, contracts and acceptance criteria are written in `docs/specs/` and approved before its code | A commit that touches `infra/`, `pipelines/` or `tools/` must carry a `Spec:` trailer naming a section of an existing spec; the commit hook rejects it otherwise |
| No AI attribution | Commits are mine, reviewed and approved; no tool signs them | The same hook rejects attribution lines |
| Spec and code never repeat each other | The spec owns the why and the contracts; the code owns values, flags and versions; a doc links to the file instead of restating it | A rule in AGENTS.md, checked in review |
| Every external fact sourced | A version, a default, a project's behaviour carries its link in the same paragraph or table row | The independent read: a fact without its source is a finding |
| An independent read | Before I review a phase, the data path's spec or a public page, a second agent reads it against its sources | Its findings and their fixes: case 2 below |
| Runbooks as each step runs | Every repeatable step lands in its runbook with its real output and a check, before the next step starts | [The runbooks](runbooks/README.md), from a fresh laptop to a clean machine |
| A shared machine treated as someone else's | The lab runs on an Ubuntu machine in the office with two GPUs, shared with the AI team. Every step on it is shown first (a playbook as a dry run with its diff) and runs only after my go for that step; every addition has its removal | A teardown playbook, and a scan for anything the lab left behind |
| Choices planned before work | Several ways to do a step are laid out as a plan I comment on, revision by revision, before any change | The agent's plan mode, which cannot change anything but the plan |

## Three errors caught before they shipped

Each one is a real error in the data path, the phase that copies the client's OCR tables once, replays their history
into the lab's own Postgres, and streams every change through Kafka into a lakehouse: bronze keeps every change as it
arrived, silver the current state of each row ([the outcomes](../README.md#the-outcomes-so-far)). Each was caught by
the method, not by luck.

### 1. People's names, found before the copy was written

**What could have shipped:** the copy of the client's tables was meant to hold no person. The spec already left out
the columns that point at a user by foreign key.

**What caught it:** a read-only pass over the catalogs of the client's development and staging databases, before any
code (2026-11-01), printing only counts, key names and email domains, never a value that names a person:

| Found | Where |
|---|---|
| Two columns of user ids with no foreign key to say so | The OCR service's tables: `document.owner_user`, `document_run.triggered_by` (12 distinct ids in development) |
| Users' names inside template titles | 9 of 79 templates in development, 25 of 99 in staging |
| The author's name in each result's header and in every saved version | Results and their history |

**The fix:** all three went into the spec's copy contract first, then into the code: the columns are left behind in
the SELECT, the titles not copied, the authors stripped from every version. The acceptance check passed: no column
naming a person, no author field, and no copied row of the Odoo tables holding a string equal to a user's name.

### 2. Seventeen findings on the data path's design

**What could have shipped:** a spec that read well and was wrong in places only a careful reader of the sources
would see.

**What caught it:** the independent read (2026-10-31), against the design, the lab's measured facts and the
projects' documentation: 17 findings. Those that changed the design went into the spec as proposals for my approval,
before any code. Four of them:

| Finding | The fix in the spec |
|---|---|
| People's names would also leave through every table's `create_uid` and `write_uid`, and each history version's author | One general rule: no column that points at a user, history authors stripped |
| A template's row reaches 72 MB, most of it its history; Kafka's default record batch limit is 1,048,588 bytes ([`max.message.bytes`](https://kafka.apache.org/43/generated/topic_config.html)) | The history is replayed version by version and never becomes one event; the copy's manifest records the largest event (0.71 MB), the topics' limits are set above it (2 MB), and an acceptance check sends that event through |
| Replaying a row with its final state shows the future: a run would appear finished at its start | The replay writes each row's past first, version by version, at the time each version was saved |
| The silver table's MERGE fails when one batch holds several events for one key | The newest event per key wins, by its position in the write-ahead log |

### 3. The gold join: from 70 to 200

**What was at stake:** the human gold set is the reference later phases test against: each crop a person kept, joined
to the region the OCR service detected and cut it from. A crop names its page image by an attachment id; each page
has a plain and an annotated image, with a box stored for each.

**What caught it:** the join was prototyped first in plain Python over the copy's files (2026-11-01), against a
number already known: 200 of the 250 crops join, and 50 point at page images the client's system no longer holds.

```text
first try        joined 70    (development 35, staging 35)
id by regex      joined 192   (86, 106)
per-render box   joined 200   (90, 110); the other 50 without a page image
```

**The fix**, one detail per step:
- 180 of the 250 crop links end in `?unique=...`, so the attachment id is read with a pattern, not taken as the
  link's last segment.
- The last 8 crops were cut from the annotated page image, so they match the box as drawn on that render, not the
  plain box.

The prototype found both causes offline, in minutes, before any Spark run. Both details went into the spec and the
Spark job, which wrote the same 200 joined picks and 50 exclusions, each with its reason, and read them back the same
twice.

## Where to read the rules

- [AGENTS.md](../AGENTS.md): every rule; those set during the lab carry the date I set them.
- [The commit hook](../tools/hooks/commit-msg) and [the docs checker](../tools/check-docs.py): the rules a machine
  checks.
- [The runbooks](runbooks/README.md): what following the rules leaves behind.
