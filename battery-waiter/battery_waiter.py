#!/usr/bin/env python3
"""battery-waiter (BNB-TOOLS T34) - wait for a quiet window, then run a command.

A heavy test suite run under load gives flaky failures: timeouts,
temp-file errors, and wall-clock proofs that fail for no code reason.
This tool waits until the machine is quiet (low load and enough free
space in the temp dir), then runs the command you give it. If no quiet
window shows up within the max wait (default 45 minutes), it runs the
command anyway and says so plainly.

The quiet window needs ALL of these at once (the load-gate rule, proven
in the Reblend UI9 verify, 2026-11-15 - load1 alone lags and lies):
  - 1-minute load average under 2.5 AND 5-minute load average under 2.5
  - fewer than 4 runnable processes (the first number of the "n/m"
    field in /proc/loadavg)
  - at least 300 MB free in the temp dir (TMPDIR, or /tmp)

Usage:
  python3 battery_waiter.py [--max-wait MINUTES] [--interval SECONDS]
      [--max-load LOAD] [--max-runnable N] [--min-tmp-mb MB]
      [--tmp-dir PATH] [--debug-report PATH] [--] COMMAND [ARGS...]

Examples:
  python3 battery_waiter.py -- python3 -m unittest discover -s tests
  python3 battery_waiter.py --max-wait 90 -- python3 -m pytest tests/

The command's exit code passes through unchanged. The tool itself is
standard library only and runs under plain python3.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

VERSION = "0.1.0"

DEFAULT_MAX_LOAD = 2.5
DEFAULT_MAX_RUNNABLE = 4
DEFAULT_MIN_TMP_MB = 300
DEFAULT_MAX_WAIT_MINUTES = 45.0
DEFAULT_INTERVAL_SECONDS = 30.0

MB = 1024 * 1024


# ---------------------------------------------------------------- readings

class LoadReading:
    """One load snapshot. runnable is None where it cannot be read."""

    def __init__(self, load1, load5, runnable):
        self.load1 = load1
        self.load5 = load5
        self.runnable = runnable

    def __repr__(self):  # pragma: no cover - debugging aid
        return "LoadReading(%r, %r, %r)" % (
            self.load1, self.load5, self.runnable)


def parse_loadavg_text(text):
    """Parse /proc/loadavg text into a LoadReading, or None.

    Format: "load1 load5 load15 runnable/total last_pid". The runnable
    count is the number before the slash in the 4th field.
    """
    try:
        fields = text.split()
        load1 = float(fields[0])
        load5 = float(fields[1])
        runnable = int(fields[3].split("/")[0])
    except (IndexError, ValueError):
        return None
    return LoadReading(load1, load5, runnable)


def read_load():
    """Read the current load, or None if it cannot be read at all.

    Prefers /proc/loadavg (it carries the runnable count). Falls back
    to os.getloadavg on systems without /proc, with runnable unknown.
    """
    try:
        with open("/proc/loadavg", encoding="utf-8") as fh:
            reading = parse_loadavg_text(fh.read())
        if reading is not None:
            return reading
    except OSError:
        pass
    try:
        load1, load5, _load15 = os.getloadavg()
    except OSError:
        return None
    return LoadReading(load1, load5, None)


def read_tmp_free_mb(tmp_dir):
    """Free space in the temp dir, in MB, or None if it cannot be read."""
    try:
        return shutil.disk_usage(tmp_dir).free / MB
    except OSError:
        return None


# ---------------------------------------------------------------- the gate

def window_clear(reading, tmp_free_mb, max_load, max_runnable,
                 min_tmp_mb):
    """Is the window quiet? Returns (clear, blockers).

    blockers names every check that failed: "load1", "load5",
    "runnable", "tmp", or "load unknown" / "tmp unknown" when a
    reading could not be taken at all. An unreadable load or temp
    dir blocks the window: the tool cannot prove the machine is
    quiet, so it waits (and still runs the command when the max
    wait expires). A runnable count that cannot be read (no /proc)
    is skipped, not blocking: the two load averages still gate.
    """
    blockers = []
    if reading is None:
        blockers.append("load unknown")
    else:
        if reading.load1 >= max_load:
            blockers.append("load1")
        if reading.load5 >= max_load:
            blockers.append("load5")
        if (reading.runnable is not None
                and reading.runnable >= max_runnable):
            blockers.append("runnable")
    if tmp_free_mb is None:
        blockers.append("tmp unknown")
    elif tmp_free_mb < min_tmp_mb:
        blockers.append("tmp")
    return (not blockers, blockers)


def describe(reading, tmp_free_mb):
    """One-line numbers for a status line, "?" where unknown."""
    if reading is None:
        load_part = "load1 ?, load5 ?, runnable ?"
    else:
        runnable = ("?" if reading.runnable is None
                    else str(reading.runnable))
        load_part = "load1 %.2f, load5 %.2f, runnable %s" % (
            reading.load1, reading.load5, runnable)
    tmp_part = ("tmp ?" if tmp_free_mb is None
                else "tmp %d MB free" % int(tmp_free_mb))
    return load_part + ", " + tmp_part


def format_duration(seconds):
    """Short human duration: "45s", "2m 30s", "1h 05m"."""
    total = int(round(seconds))
    if total < 60:
        return "%ds" % total
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return "%dm %02ds" % (minutes, secs)
    hours, minutes = divmod(minutes, 60)
    return "%dh %02dm" % (hours, minutes)


# ---------------------------------------------------------------- the wait

def wait_for_window(probe, max_wait_s, interval_s, max_load,
                    max_runnable, min_tmp_mb, out, log=None):
    """Poll until the window clears or the max wait expires.

    probe() returns (reading, tmp_free_mb). Returns
    (outcome, waited_seconds, reading, tmp_free_mb) where outcome is
    "clear" or "expired". Prints a status line on every poll.
    """
    start = time.monotonic()
    deadline = start + max_wait_s
    while True:
        reading, tmp_free_mb = probe()
        clear, blockers = window_clear(
            reading, tmp_free_mb, max_load, max_runnable, min_tmp_mb)
        waited = time.monotonic() - start
        numbers = describe(reading, tmp_free_mb)
        if clear:
            line = ("Window clear after %s: %s. "
                    "Running the command now."
                    % (format_duration(waited), numbers))
            print(line, file=out, flush=True)
            if log is not None:
                log.action(line)
            return ("clear", waited, reading, tmp_free_mb)
        if time.monotonic() >= deadline:
            line = ("Max wait of %s reached and the window is still "
                    "busy: %s. Waiting on: %s. "
                    "Running the command anyway."
                    % (format_duration(max_wait_s), numbers,
                       ", ".join(blockers)))
            print(line, file=out, flush=True)
            if log is not None:
                log.action(line)
            return ("expired", waited, reading, tmp_free_mb)
        line = ("still busy (waited %s): %s. Waiting on: %s."
                % (format_duration(waited), numbers,
                   ", ".join(blockers)))
        print(line, file=out, flush=True)
        if log is not None:
            log.info(line)
        remaining = deadline - time.monotonic()
        time.sleep(min(interval_s, remaining))


# ---------------------------------------------------------------- the run

def check_command(name):
    """Plain-words problem with a command name, or None if it runs.

    Checks before waiting, so a typo does not cost a 45-minute wait.
    """
    if shutil.which(name) is not None:
        return None
    if "/" in name and os.path.exists(name):
        return ("'%s' exists but is not executable." % name)
    return "command not found: '%s'." % name


def run_command(argv):
    """Run the command with stdio passed through; return its exit code.

    A command killed by a signal reports 128 + signal, the shell
    convention, so the caller still gets a plain exit code.
    """
    proc = subprocess.run(argv)
    if proc.returncode < 0:
        return 128 + abs(proc.returncode)
    return proc.returncode


# ---------------------------------------------------------------- CLI

class PlainParser(argparse.ArgumentParser):
    """argparse that fails with a plain error and exit 1, no traceback."""

    def error(self, message):
        print("Error: %s" % message, file=sys.stderr)
        print("Run with --help to see the options.", file=sys.stderr)
        raise SystemExit(1)


def build_parser():
    parser = PlainParser(
        prog="battery_waiter.py",
        description=(
            "Wait for a quiet window (low load and enough free temp "
            "space), then run a command. If no quiet window shows up "
            "within the max wait, the command runs anyway."))
    parser.add_argument(
        "--max-wait", type=float, default=DEFAULT_MAX_WAIT_MINUTES,
        metavar="MINUTES",
        help="longest to wait for a quiet window, in minutes "
             "(default: 45)")
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_SECONDS,
        metavar="SECONDS",
        help="seconds between quiet-window checks (default: 30)")
    parser.add_argument(
        "--max-load", type=float, default=DEFAULT_MAX_LOAD,
        metavar="LOAD",
        help="load1 and load5 must BOTH be under this (default: 2.5)")
    parser.add_argument(
        "--max-runnable", type=int, default=DEFAULT_MAX_RUNNABLE,
        metavar="N",
        help="runnable process count must be under this (default: 4)")
    parser.add_argument(
        "--min-tmp-mb", type=float, default=DEFAULT_MIN_TMP_MB,
        metavar="MB",
        help="free temp space needed, in MB (default: 300)")
    parser.add_argument(
        "--tmp-dir", default=None, metavar="PATH",
        help="temp dir to check (default: TMPDIR, or /tmp)")
    parser.add_argument(
        "--debug-report", default=None, metavar="PATH",
        help="write a debug report to this file when done")
    parser.add_argument(
        "--version", action="version",
        version="battery-waiter %s" % VERSION)
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="the command to run, after --")
    return parser


def _close_logger(log):
    """Close a DebugLogger's handlers so its temp dir can go away."""
    for handler in list(log.logger.handlers):
        try:
            handler.close()
        except Exception:
            pass
        log.logger.removeHandler(handler)


def main(argv=None, out=None, probe=None):
    """Run the tool. Returns the exit code (the command's, usually).

    out defaults to stdout; probe is a test hook that replaces the
    real machine readings with probe() -> (reading, tmp_free_mb).
    """
    if out is None:
        out = sys.stdout
    args = build_parser().parse_args(argv)

    if args.max_wait <= 0:
        print("Error: --max-wait must be more than 0 minutes, got %s."
              % args.max_wait, file=sys.stderr)
        return 1
    if args.interval <= 0:
        print("Error: --interval must be more than 0 seconds, got %s."
              % args.interval, file=sys.stderr)
        return 1
    if args.max_load <= 0:
        print("Error: --max-load must be more than 0, got %s."
              % args.max_load, file=sys.stderr)
        return 1
    if args.max_runnable < 1:
        print("Error: --max-runnable must be at least 1, got %s."
              % args.max_runnable, file=sys.stderr)
        return 1
    if args.min_tmp_mb < 0:
        print("Error: --min-tmp-mb cannot be negative, got %s."
              % args.min_tmp_mb, file=sys.stderr)
        return 1

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("Error: no command given. Give the command to run after "
              "the options, for example: battery_waiter.py -- python3 "
              "-m unittest discover -s tests", file=sys.stderr)
        return 1

    problem = check_command(command[0])
    if problem is not None:
        print("Error: %s" % problem, file=sys.stderr)
        return 1

    tmp_dir = args.tmp_dir or os.environ.get("TMPDIR") or "/tmp"

    log = None
    log_dir = None
    if args.debug_report:
        try:
            from debug_log import DebugLogger
        except ImportError:
            print("Error: debug_log.py is missing next to "
                  "battery_waiter.py, so no debug report can be "
                  "written.", file=sys.stderr)
            return 1
        log_dir = tempfile.mkdtemp(prefix="battery-waiter-")
        log = DebugLogger("battery-waiter", VERSION, log_dir=log_dir)
        log.set_setting("command", shlex.join(command))
        log.set_setting("max_wait_minutes", args.max_wait)
        log.set_setting("interval_seconds", args.interval)
        log.set_setting("max_load", args.max_load)
        log.set_setting("max_runnable", args.max_runnable)
        log.set_setting("min_tmp_mb", args.min_tmp_mb)
        log.set_setting("tmp_dir", tmp_dir)
        log.install_crash_handler()

    print("Will run: %s" % shlex.join(command), file=out, flush=True)
    print("Waiting for a quiet window: load1 and load5 under %s, "
          "runnable under %d, temp free at least %d MB in %s. "
          "Will wait up to %s, then run anyway."
          % (args.max_load, args.max_runnable, args.min_tmp_mb,
             tmp_dir, format_duration(args.max_wait * 60)),
          file=out, flush=True)
    if log is not None:
        log.action("wait started for: %s" % shlex.join(command))

    if probe is None:
        def probe():
            return (read_load(), read_tmp_free_mb(tmp_dir))

    try:
        outcome, waited, _reading, _tmp = wait_for_window(
            probe, args.max_wait * 60, args.interval, args.max_load,
            args.max_runnable, args.min_tmp_mb, out, log)
    except KeyboardInterrupt:
        print("Stopped while waiting. The command did not run.",
              file=out, flush=True)
        if log is not None:
            log.action("wait stopped by the user")
            _close_logger(log)
        return 130

    if log is not None:
        log.action("window %s after %s"
                   % (outcome, format_duration(waited)))
    run_start = time.monotonic()
    code = run_command(command)
    run_time = time.monotonic() - run_start
    print("Done: waited %s, command ran for %s, exit code %d."
          % (format_duration(waited), format_duration(run_time), code),
          file=out, flush=True)
    if log is not None:
        log.action("command finished with exit code %d" % code)
        try:
            path = log.generate_report(args.debug_report)
        except OSError as exc:
            print("Warning: could not write the debug report to %s: %s"
                  % (args.debug_report, exc), file=out, flush=True)
        else:
            print("Debug report written to %s." % path,
                  file=out, flush=True)
        _close_logger(log)
        shutil.rmtree(log_dir, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
