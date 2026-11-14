# T3 — post-merge-battery-runner

Pairs with skill **S8** (post-merge battery + baseline failure-set comparison).

Waits for a stable window (no tree changes mid-merge), runs the battery, diffs the failure list against a baseline, reports only the delta.

## What it does

1. **Wait** — polls the tree's newest mtime until it has been quiet for `--stable-seconds` (default 60), checking every `--poll-seconds` (default 5), giving up after `--max-wait-seconds` (default 3600). Optionally also waits until no process matches a `--wait-for-process` pgrep pattern (own pid excluded).
2. **Run** — runs the command after `--` (any command, e.g. `python3 -m unittest discover`), captures output to `--log`.
3. **Diff** — extracts failures (unittest `FAIL:`/`ERROR:` lines, pytest `FAILED` lines, or `--failure-regex`) and diffs them against `--baseline` (one failure id per line).
4. **Report** — prints only the delta: NEW failures, FIXED failures, unchanged count.

Exit codes: 0 = failure set identical to baseline (clean), 1 = new failures, 2 = window never cleared or command could not run.

## Why this is a script file

The wait-for-window watchdog **must** live in a file, never as `bash -c`: a `bash -c` watchdog whose own command text contains the pgrep match string (including the unittest invocation itself) matches its own process forever and the window never reads clear (AGENTS.md, Forge 2026-11-12). This tool *is* that script file — and its stability check watches the tree (mtimes), not a process pattern, so it cannot self-match at all.

Check free disk space before you run it: the suite needs at least 300 MB free on /tmp — see S8 (post-merge-battery) for the gate, the invalid-run triage, and the ceiling-recalibration rule. A run killed by disk-full is invalid, not a failure set.

## Requirements

Python 3.8+, stdlib only. No network. `pgrep` only needed for `--wait-for-process`.

## Usage

```bash
# Wait for 60s of quiet, run the suite, diff vs baseline
python3 battery.py --tree ./my-project --stable-seconds 60 \
    --baseline baseline-failures.txt --log battery.log \
    -- python3 -m unittest discover -s tests

# Also wait out any running unittest process first
python3 battery.py --tree ./my-project \
    --wait-for-process 'python -m unittest' \
    --baseline baseline-failures.txt \
    -- python3 -m unittest discover -s tests

# Baseline format: one failure id per line, e.g.
# test_core.StreamingRenderTests.test_anchor
```

## Smoke test

```bash
bash smoke_test.sh
```

Runs against a tiny dummy unittest suite with a known baseline: shows a clean run, then a run with a newly-failing test flagged.
