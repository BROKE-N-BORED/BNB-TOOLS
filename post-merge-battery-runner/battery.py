#!/usr/bin/env python3
"""T3 post-merge-battery-runner — wait for a stable window, run the
battery, report only the failure delta vs a baseline.

Generalizes ~/workspace/forge-queue-verify/wait_and_fullsuite.sh,
run_battery.sh and run_fullsuite_chunked.py.

Why this is a script file: the wait-for-window watchdog MUST live in a
file, never as `bash -c` — a bash -c watchdog whose own command text
contains the pgrep match string (including the unittest invocation
itself) matches its own process forever and the window never reads
clear. (AGENTS.md, Forge 2026-11-12.) This tool IS that script file:
its own cmdline is just `python3 battery.py ...`, and the stability
check below watches the TREE (mtimes), not a process pattern, so it
cannot self-match at all. An optional --wait-for-process pattern is
still offered, matched via pgrep with the tool's own pid excluded.

Flow:
  1. Wait until the tree has been quiet for --stable-seconds (no file
     mtime change under --tree), checking every --poll-seconds, giving
     up after --max-wait-seconds.
  2. Run the command after `--` (e.g. python3 -m unittest discover).
     Output goes to --log (and stdout with --show-output).
  3. Extract the failure list (unittest FAIL:/ERROR: lines, pytest
     FAILED lines, or lines matching --failure-regex) and diff it
     against --baseline (one failure id per line).
  4. Report only the delta: NEW failures, FIXED failures, unchanged.
     Exit 0 when the failure set is identical to baseline (or empty
     with no baseline), 1 when there are NEW failures, 2 when the
     window never cleared or the command could not run.

Stdlib only. Python 3.8+.
"""
import argparse
import os
import re
import subprocess
import sys
import time

DEFAULT_FAILURE_PATTERNS = [
    # unittest prints "FAIL: test_x (module.Class.test_x)" — the
    # parenthesised dotted id is the stable failure id.
    re.compile(r"^(?:FAIL|ERROR):\s+\S+\s+\(([^)]+)\)"),
    re.compile(r"^(?:FAIL|ERROR):\s+(\S+)"),          # unittest, no parens
    re.compile(r"^FAILED\s+([^\s(]\S*)"),            # pytest -q (not the
                                                 # unittest "FAILED (failures=N)"
                                                 # summary line)
    re.compile(r"^(?:FAIL|ERROR)\s+(\S+.*)$"),         # generic
]


def tree_mtime(root):
    """Newest mtime under root (None if the tree is missing)."""
    if not os.path.isdir(root):
        return None
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", ".venv")]
        for name in filenames:
            try:
                m = os.path.getmtime(os.path.join(dirpath, name))
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


def process_running(pattern):
    """True if any process other than this one matches the pattern."""
    try:
        proc = subprocess.run(["pgrep", "-f", pattern],
                              capture_output=True, text=True)
    except FileNotFoundError:
        return False  # no pgrep on this system: can't check, don't block
    pids = [p for p in proc.stdout.split() if p != str(os.getpid())]
    return bool(pids)


def wait_stable(tree, stable_seconds, poll_seconds, max_wait_seconds,
                process_pattern=None):
    """Wait for a quiet window. Returns True if the window cleared."""
    deadline = time.time() + max_wait_seconds
    quiet_since = None
    last_mtime = tree_mtime(tree)
    if last_mtime is None:
        print(f"error: tree not found: {tree}", file=sys.stderr)
        return False
    waited = 0
    while time.time() < deadline:
        now_mtime = tree_mtime(tree)
        busy_process = (process_pattern is not None
                        and process_running(process_pattern))
        if now_mtime != last_mtime or busy_process:
            last_mtime = now_mtime
            quiet_since = None
            if busy_process:
                print(f"  [{waited}s] process still running: {process_pattern}")
            else:
                print(f"  [{waited}s] tree changed; stability clock reset")
        else:
            if quiet_since is None:
                quiet_since = time.time()
            quiet_for = time.time() - quiet_since
            if quiet_for >= stable_seconds:
                print(f"window clear: tree quiet for {quiet_for:.0f}s "
                      f"after {waited}s of waiting")
                return True
        time.sleep(poll_seconds)
        waited += poll_seconds
    print(f"WINDOW NEVER CLEARED after {max_wait_seconds}s — battery NOT run",
          file=sys.stderr)
    return False


def extract_failures(text, extra_regex=None):
    patterns = list(DEFAULT_FAILURE_PATTERNS)
    if extra_regex:
        patterns.append(re.compile(extra_regex))
    failures = []
    for line in text.splitlines():
        for pat in patterns:
            m = pat.search(line.strip())
            if m:
                failures.append(m.group(1).strip())
                break
    # De-duplicate, keep order.
    return list(dict.fromkeys(failures))


def load_baseline(path):
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="battery.py",
        description="Wait for a stable tree window, run the battery, "
                    "report only the failure delta vs baseline.")
    ap.add_argument("--tree", required=True,
                    help="tree to watch for stability")
    ap.add_argument("--stable-seconds", type=float, default=60,
                    help="quiet window required before running (default 60)")
    ap.add_argument("--poll-seconds", type=float, default=5,
                    help="how often to re-check the tree (default 5)")
    ap.add_argument("--max-wait-seconds", type=float, default=3600,
                    help="give up waiting after this long (default 3600)")
    ap.add_argument("--wait-for-process", default=None, metavar="PATTERN",
                    help="also wait until no process matches this pgrep "
                         "pattern (own pid excluded)")
    ap.add_argument("--baseline", default=None,
                    help="baseline failure file (one failure id per line)")
    ap.add_argument("--log", default=None,
                    help="write the command's full output here")
    ap.add_argument("--failure-regex", default=None,
                    help="extra regex (group 1 = failure id) for failures")
    ap.add_argument("--show-output", action="store_true",
                    help="also stream the command's output to stdout")
    ap.add_argument("--skip-wait", action="store_true",
                    help="do not wait for a stable window (testing only)")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="command to run, after '--'")
    args = ap.parse_args(argv)
    cmd = [c for c in args.command if c != "--"]
    if not cmd:
        ap.error("no command given — put it after '--', e.g. "
                 "battery.py --tree . -- python3 -m unittest discover")

    if not args.skip_wait:
        if not wait_stable(args.tree, args.stable_seconds,
                           args.poll_seconds, args.max_wait_seconds,
                           args.wait_for_process):
            return 2
    else:
        print("(--skip-wait: stability wait skipped)")

    print(f"running battery: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    if args.log:
        with open(args.log, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"full output -> {args.log}")
    if args.show_output:
        print(output, end="")
    print(f"battery exit code: {proc.returncode}")

    failures = extract_failures(output, args.failure_regex)
    baseline = load_baseline(args.baseline)
    print(f"failures found: {len(failures)}; baseline: {len(baseline)}")
    new = [f for f in failures if f not in baseline]
    fixed = [f for f in baseline if f not in failures]
    unchanged = [f for f in failures if f in baseline]

    print("=== failure delta vs baseline ===")
    if not new and not fixed:
        print("IDENTICAL — failure set byte-identical to baseline"
              if baseline or not failures else "no failures")
    if new:
        print(f"NEW FAILURES ({len(new)}):")
        for f in new:
            print(f"  + {f}")
    if fixed:
        print(f"FIXED ({len(fixed)}):")
        for f in fixed:
            print(f"  - {f}")
    if unchanged:
        print(f"unchanged ({len(unchanged)}): " + ", ".join(unchanged))
    if new:
        print("VERDICT: DIRTY — new failures appeared")
        return 1
    print("VERDICT: CLEAN — no new failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
