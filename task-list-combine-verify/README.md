# task-list-combine-verify

Verify a combined task list against the source lists it was built from:
every source task traced exactly once, combined IDs unique and
contiguous, tiers contiguous, statuses adding up. Pairs with BNB SKILLS
**audit-each-one-combine** (S64, the workflow that produces the combined list
this tool checks).

## What it does

When several per-item audits each produce their own task list, the lists
get combined into one prioritized list — deduped, re-tiered, re-numbered.
A combine done by hand drops tasks and invents entries silently. This
checker proves the combine lost nothing and invented nothing:

- every source task is traced to exactly one combined entry (untraced
  tasks and double-traced tasks are named);
- every combined entry references only source tasks that exist, and
  covers at least one (an entry covering nothing is an invented entry);
- combined IDs are unique and contiguous (`C1`–`CN`, no gaps, none past
  the count);
- every tier is one of P0/P1/P2 and no tier is skipped;
- every status is one of `not started`, `queued`, `in flight`, `done`,
  `blocked`, and the status counts add up to the combined total.

## Usage

```bash
python3 combine_verify.py --sources sources.json --combined combined.json
python3 combine_verify.py --sources sources.json --combined combined.json --id-prefix T
```

Exit code 0 = all checks pass. Exit code 1 = at least one check failed,
with every failure named on stdout. Exit code 2 = the inputs could not
be read or parsed.

Input format (JSON). Sources file: a list of source lists, each with a
`name` and `tasks` (each task: `id`, `title`; optional `tier`,
`status`). Combined file: a list of entries, each with `id`, `title`,
`tier`, `status`, and `sources` (list of source task ids it covers).

```json
// sources.json
[{"name": "S2-secrets", "tasks": [
  {"id": "S2-T1", "title": "rclone protection"},
  {"id": "S2-T2", "title": "history scrub"}
]}]

// combined.json
[{"id": "C1", "title": "rclone protection", "tier": "P0",
  "status": "in flight", "sources": ["S2-T1"]},
 {"id": "C2", "title": "history scrub", "tier": "P1",
  "status": "not started", "sources": ["S2-T2"]}]
```

## Smoke test

```bash
python3 tests/smoke_test.py
```

22 checks, no network: the good combine passes with correct counts, and
each defect class is caught and named (untraced task, entry covering
nothing, duplicated id, gap in the sequence, unknown source reference,
double-traced source, bad tier, skipped tier, bad status, source id in
two lists), plus CLI end-to-end (exit 0/1/2).

## Source

This checker automates the verification the Code Forge security thread
ran by script on 2026-11-12 when it combined six cluster audits
(121 tasks) into one list of 117: IDs C1–C117 all present exactly once,
tiers contiguous, every source task traced to its combined entry,
statuses adding up (4 in flight, 4 queued, 109 not started). The
hand-run version caught nothing because the combine was clean — the
tool exists so the next combine gets the same proof without writing the
script from scratch.
