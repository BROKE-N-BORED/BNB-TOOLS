# T16 — token-burn-rate-tracker

Baseline snapshot → scheduled recheck → tokens/day + pool-lifetime
estimate. Pairs with BNB SKILLS **S40** (token burn-rate baseline +
scheduled recheck). No network — a plain JSON log.

## Workflow

1. **Baseline** — record total tokens used + pool size, with a source note:
   ```bash
   python3 token_tracker.py snapshot --used 123456789 --pool 1000000000 \
       --source "subscription status page" --date 2026-10-31
   ```
2. **Recheck days later** (same command, new numbers; `--date` defaults to
   today).
3. **Report**:
   ```bash
   python3 token_tracker.py report
   python3 token_tracker.py report --json
   python3 token_tracker.py list
   ```

## What the report shows

- tokens/day since baseline (overall) + a per-day breakdown between each
  pair of consecutive snapshots (so a fast week shows up separately from a
  slow one)
- remaining pool and lifetime at the measured pace, with the projected
  run-out date
- the caveat, on every report: **the pool may still be untouched if the
  weekly limit hasn't been exhausted** — the tracker measures what the
  snapshots say, not the pool's internal state

Worked example (the audit's case, verified by hand in the smoke test):
baseline Oct 31 at 100.0M used → recheck Nov 3 at 139.3M used is 3 days;
+39.3M over 3 days is exactly 13.1M/day; a 1B pool with 860.7M left lasts
~65.7 days at that pace (runs out ~Jan 7, 2027).

## Log file

Default `token-log.json` next to the script; override with `--log`.
Snapshots are appended and kept in date order. Nothing is ever overwritten.

## Requirements

Python 3 stdlib only.
