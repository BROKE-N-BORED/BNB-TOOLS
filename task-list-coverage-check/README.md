# task-list-coverage-check

Check a task list covers every audit finding, mechanically instead of by
eye. Pairs with BNB SKILLS **audit-findings-task-list-merge** (S65): after
folding a new audit's findings into an existing task list, this tool
verifies the merge before the merged list is reported.

## What it does

- Reads a findings file (one finding per line, `ID: description`) and a
  task-list Markdown file (tasks as headings or list items starting with
  a task ID — `T1`, `T11`, `C117`, `T2-4` — each with a `Covers: ID1,
  ID2` line naming the findings it covers).
- Reports, and fails on:
  1. findings no task covers (the dropped finding);
  2. finding IDs a task references that do not exist in the findings
     file (a typo in the coverage map);
  3. duplicate task IDs or duplicate finding IDs (ambiguous coverage).
- Double coverage — two tasks covering the same finding — is allowed
  and passes: untidy, not a dropped finding.
- Prints a reconciliation (findings total / covered / uncovered, task
  count) in plain text, or as JSON with `--json`.

## Usage

```bash
python3 coverage_check.py findings.txt tasks.md
python3 coverage_check.py findings.txt tasks.md --json
```

Exit code 0 = pass (every finding covered, no unknown references, no
duplicate IDs). Exit code 1 = fail. Exit code 2 = usage error (missing
file, or no findings parsed).

Example findings file:

```
# verdict findings
V-01: probe loads the base model twice
V-02: maternion typo in the README
V-03: torch.load pickle risk on import
```

Example task list:

```markdown
## T11 — probe loads the base model twice
Covers: V-01

## T12 — maternion typo
Covers: V-02
```

## Where this comes from

- STELLA ✨ Development thread (2026-11-12 ~21:00 EST): a verdict's 33
  findings folded into the existing list — "91 tasks covering all 214
  findings (181 from audits #1–#4 plus 33 from the verdict, verified by
  script)". The script that did the verifying was ad hoc; this tool is
  the reusable version of it.
- STUDY DASHBOARD DEV thread (2026-11-12 ~19:00 EST): the 23-task list
  carried "a coverage map at the end of the file proving nothing got
  dropped" — this tool checks that map mechanically.

## Smoke test

```bash
python3 -m unittest discover -s tests -v
```

12 tests, all green (verified by the Delta 2 Worker C run, 2026-11-13).

## Requirements

Python 3, standard library only.
