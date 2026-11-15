# Changelog

## v0.1.0 - 2026-11-15

First release.

- Waits for a quiet window, then runs the command: load1 and
  load5 both under 2.5, runnable processes under 4, at least
  300 MB free in the temp dir. Polls every 30 seconds by
  default, prints a plain status line on each poll naming what
  it is waiting on and the current numbers.
- Runs the command anyway when the max wait expires (default
  45 minutes) and says which happened: window clear, or max
  wait reached. Reports the wait time and the run result at
  the end, and passes the command's exit code through
  unchanged.
- Checks the command exists before waiting, so a typo does
  not cost a 45-minute wait. Plain-words errors, exit 1,
  never a traceback: no command given, command not found, a
  file that exists but is not executable, bad threshold
  values.
- `--debug-report PATH` writes a debug report (T21 debug log
  layer, copied unmodified) with the thresholds, the command,
  and the wait outcome. The log file lives in a temp dir, so
  no `logs/` folder ever lands in the tree.
- The generic form of the Code Forge overnight test-battery
  waiter (Nov 14): the saga's load gate, temp-space gate,
  and stale-verdict lesson, as one small chainable tool.
