# T34 - battery-waiter

A small chainable CLI: wait for a quiet window, then run a
heavy command (usually a test suite). If no quiet window shows
up within the max wait, it runs the command anyway and says so.

The name is about test batteries, not laptop batteries: it
waits for the right moment to run a battery of tests.

## What it does

```bash
python3 battery_waiter.py -- python3 -m unittest discover -s tests
```

It polls the machine about every 30 seconds and runs the
command when the window is quiet: load1 and load5 both under
2.5, fewer than 4 runnable processes, and at least 300 MB free
in the temp dir. Each poll prints one plain status line with
the current numbers and what it is still waiting on. When the
max wait expires (default 45 minutes) it runs the command
anyway and says the wait expired, so the run's log always
shows which one happened. The command's exit code passes
through unchanged.

## Why it exists: the Code Forge saga

On the night of Nov 14, the Code Forge overnight test battery
needed a quiet machine and did not have one. The shared
sandbox was running several suites at once, so a small waiter
script watched for a clear window and then ran the heavy
suite. Three things went wrong, and each one is a feature of
this tool:

1. **A VM restart killed the waiter mid-wait.** The verdict
   file on disk was from an earlier run, and it got re-read
   afterwards as if it were fresh. The run that was supposed
   to produce a new verdict had never happened. Lesson: a
   verdict must carry its own timestamp, so a later reader
   can tell fresh from stale (see below). This tool cannot
   survive a restart either, and it does not pretend to: it
   is a plain foreground process, and if the machine restarts
   you re-run it. What it does is make the run it guards
   honest about when it waited, when it ran, and why.
2. **/tmp dipped to 19 MB.** The sandbox /tmp is a small
   tmpfs, and other threads' suites were filling it. Temp
   DB-file failures in the battery looked like product
   failures until the same tests went green run solo: the
   failures were environmental, not code. Lesson: free temp
   space is part of the gate, not an afterthought. This tool
   treats under 300 MB free in the temp dir as a busy
   window (the threshold comes from the Nov 13 batch-2
   battery, where a suite run hit ENOSPC mid-run with 195
   errors).
3. **The first waiter only watched for running suites.** It
   checked with pgrep whether another suite was running, and
   said nothing about load or disk. A machine with no suite
   running can still be too loaded to measure wall-clock
   time cleanly. Lesson: gate on the machine's state, not on
   a process list.

## The load-gate rule

The window needs ALL of these at once:

- load1 under 2.5 AND load5 under 2.5
- runnable process count under 4
- temp dir free space at least 300 MB

Load1 alone lags and lies. The case that proved it (Reblend
UI9 verify, 2026-11-15): the 1-minute average read 2.49, a
"quiet" number, while the 5-minute average sat at 6+ and
16 to 28 processes were runnable. A wall-clock proof started
in that window still failed, because the machine was not
quiet at all, the 1-minute average just had not caught up
yet. So the gate checks both averages and the runnable
count, read from /proc/loadavg: the runnable count is the
number before the slash in the 4th field ("n/m").

The runnable default (under 4) is a judgment call, not a
measured constant: a quiet machine typically has 1 or 2
processes runnable, and the proven-busy case had 16 to 28.
If your machine idles higher, raise it with
`--max-runnable`. All thresholds are flags, not hard code.

## Usage

```bash
python3 battery_waiter.py [options] [--] COMMAND [ARGS...]
```

| Option | Default | What it does |
| --- | --- | --- |
| `--max-wait MINUTES` | 45 | Longest to wait, then run anyway |
| `--interval SECONDS` | 30 | Seconds between quiet-window checks |
| `--max-load LOAD` | 2.5 | load1 and load5 must BOTH be under this |
| `--max-runnable N` | 4 | Runnable process count must be under this |
| `--min-tmp-mb MB` | 300 | Free temp space needed, in MB |
| `--tmp-dir PATH` | TMPDIR, or /tmp | Temp dir to check |
| `--debug-report PATH` | none | Write a debug report to this file when done |

Examples:

```bash
# Wait, then run the suite (the saga's shape)
python3 battery_waiter.py -- python3 -m unittest discover -s tests

# Wait up to 90 minutes, checking every 60 seconds
python3 battery_waiter.py --max-wait 90 --interval 60 -- ./run_suite.sh

# Looser gate on a busier machine, with a debug report
python3 battery_waiter.py --max-load 4 --max-runnable 8 \
    --debug-report /tmp/wait-report.txt -- make test
```

The command is checked before waiting starts: a typo or a
missing command fails at once with a plain error instead of
costing a 45-minute wait.

## What it prints

While waiting, one line per poll:

```text
Will run: python3 -m unittest discover -s tests
Waiting for a quiet window: load1 and load5 under 2.5, runnable under 4, temp free at least 300 MB in /tmp. Will wait up to 45m 00s, then run anyway.
still busy (waited 30s): load1 3.10, load5 2.80, runnable 6, tmp 412 MB free. Waiting on: load1, load5, runnable.
```

When the window clears, or when the wait expires, it says
which one happened, then runs the command with its output
passed straight through:

```text
Window clear after 2m 30s: load1 1.20, load5 1.10, runnable 2, tmp 412 MB free. Running the command now.
```

or:

```text
Max wait of 45m 00s reached and the window is still busy: load1 4.10, load5 3.90, runnable 9, tmp 412 MB free. Waiting on: load1, load5, runnable. Running the command anyway.
```

At the end, one summary line:

```text
Done: waited 2m 30s, command ran for 4m 12s, exit code 0.
```

## Exit codes

| Code | Meaning |
| --- | --- |
| The command's code | Normal case: the waiter's exit code is the command's |
| 1 | The waiter itself could not run: no command given, command not found, a file that exists but is not executable, a bad threshold value, or the debug log layer missing when `--debug-report` was asked for |
| 130 | Stopped with Ctrl-C while waiting; the command did not run |

Errors are plain words naming the missing thing, never a
traceback. A command killed by a signal reports 128 plus the
signal number, the shell convention.

## Timestamp your verdict

The stale-verdict lesson from the saga: if the waited-for
run writes a verdict file (a status file, a summary, a log
tail), that file must carry the time it was written. A
verdict with no timestamp cannot be told apart from a stale
one after a restart, a kill, or a run that never happened,
and the next reader will trust it either way. This tool does
not write a verdict file itself; it prints the wait and run
times to its own output so the log shows when the run
happened. Whatever your run writes, stamp it.

## Debug report

`--debug-report PATH` writes a debug report when the run
finishes, in the standard format from the T21 debug log
layer (`debug_log.py`, copied unmodified): the thresholds,
the command, the wait outcome, and the run result. The log
file lives in a temp dir created for the run and cleaned up
afterwards, so no `logs/` folder ever lands in the tree. If
the report cannot be written, you get a plain warning and
the command's exit code still passes through.

## Requirements

Python 3.8+, standard library only. No network, no account.
The load gate reads /proc/loadavg on Linux; on systems
without /proc it falls back to `os.getloadavg()` and skips
the runnable check (the two load averages still gate). If
the load or the temp dir cannot be read at all, the window
stays busy and the command runs when the max wait expires.

This is a CLI script tool, not a GUI app: it runs in the
terminal and from other scripts, and it chains with anything
that takes an exit code.

## Smoke test

```bash
bash run_tests.sh
```

37 tests, no network. Threshold logic (window clear, load1
high, load5 high, runnable high, temp low, plus boundary
and unknown-reading cases) uses injected fake readings, so
the suite never depends on the real machine load. Max-wait
expiry is tested with timeouts of a fraction of a second.
Also covered: exit-code pass-through, status-line content,
`--help`, plain-words errors, and the debug report.

## What it does not do

- It does not survive a restart. It is a foreground process;
  a VM restart kills it like any other process, and you
  re-run it. It does not queue, daemonize, or resume.
- It does not schedule. It runs once, when you run it. Put
  it in cron if you want it on a schedule.
- It does not check the machine's battery. The name is about
  test batteries.
- It does not write a verdict file for the run it guards.
  Stamp your own verdict (see above).
- It does not judge whether the run passed. It reports the
  exit code and leaves the verdict to you.
