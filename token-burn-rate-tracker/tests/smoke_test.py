#!/usr/bin/env python3
"""Smoke test for T16 token-burn-rate-tracker.

Two snapshots with known fake numbers a few days apart, then a third;
verify the computed rate + lifetime arithmetic by hand.

Hand check:
  baseline 2026-10-31 used=100,000,000 pool=1,000,000,000
  recheck  2026-11-03 used=139,300,000
    delta = 39,300,000 over 3 days -> 13,100,000/day exactly
    remaining = 1,000,000,000 - 139,300,000 = 860,700,000
    lifetime = 860,700,000 / 13,100,000 = 65.70... days
    run-out ~ 2026-11-03 + 65 days = 2027-01-07
  third    2026-11-05 used=152,400,000
    leg 2: 13,100,000 over 2 days -> 6,550,000/day
    overall: 52,400,000 over 5 days -> 10,480,000/day
    remaining 847,600,000 -> lifetime 80.88 days
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "token_tracker.py"


def run(*args, timeout=60):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    tmp = Path(tempfile.mkdtemp(prefix="t16-smoke-"))
    log = tmp / "token-log.json"

    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    snaps = [
        ("2026-10-31", 100_000_000),
        ("2026-11-03", 139_300_000),
        ("2026-11-05", 152_400_000),
    ]
    for date, used in snaps:
        p = run("--log", str(log), "snapshot", "--used", str(used),
                "--pool", "1000000000", "--source", "smoke test fake",
                "--date", date)
        print("== snapshot %s exit=%d: %s"
              % (date, p.returncode, p.stdout.strip()))
        if p.returncode != 0:
            fails.append("snapshot %s failed: %s" % (date, p.stderr))

    p = run("--log", str(log), "report", "--json")
    print("== report --json exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("report failed: %s" % p.stderr)
        print("\nSMOKE TEST: FAIL")
        return 1
    rep = json.loads(p.stdout)
    print(json.dumps(rep, indent=2))
    # Hand-checked assertions.
    if rep["days"] != 5:
        fails.append("span should be 5 days, got %r" % rep["days"])
    if rep["used_delta"] != 52_400_000:
        fails.append("used_delta wrong: %r" % rep["used_delta"])
    if abs(rep["per_day"] - 10_480_000) > 0.01:
        fails.append("per_day wrong: %r (want 10,480,000)" % rep["per_day"])
    if rep["remaining"] != 847_600_000:
        fails.append("remaining wrong: %r" % rep["remaining"])
    if abs(rep["lifetime_days"] - 847_600_000 / 10_480_000) > 0.01:
        fails.append("lifetime wrong: %r" % rep["lifetime_days"])
    legs = rep["legs"]
    if len(legs) != 2:
        fails.append("want 2 legs, got %d" % len(legs))
    else:
        if abs(legs[0]["per_day"] - 13_100_000) > 0.01:
            fails.append("leg 1 per_day wrong: %r (want 13,100,000)"
                         % legs[0]["per_day"])
        if abs(legs[1]["per_day"] - 6_550_000) > 0.01:
            fails.append("leg 2 per_day wrong: %r (want 6,550,000)"
                         % legs[1]["per_day"])

    # Two-snapshot case: the audit's exact numbers.
    log2 = tmp / "log2.json"
    for date, used in snaps[:2]:
        run("--log", str(log2), "snapshot", "--used", str(used),
            "--pool", "1000000000", "--date", date)
    p = run("--log", str(log2), "report")
    print("== two-snapshot report exit=%d" % p.returncode)
    print(p.stdout)
    if "13,100,000/day" not in p.stdout:
        fails.append("report should show 13,100,000/day")
    if "65.7 days" not in p.stdout or "2027-01-07" not in p.stdout:
        fails.append("report should show ~65.7 days, run-out 2027-01-07")
    if "CAVEAT" not in p.stdout:
        fails.append("report must print the pool-untouched caveat")

    # One snapshot is not enough for a report.
    log3 = tmp / "log3.json"
    run("--log", str(log3), "snapshot", "--used", "100",
        "--pool", "1000", "--date", "2026-11-12")
    p = run("--log", str(log3), "report")
    if p.returncode == 0:
        fails.append("report with 1 snapshot should fail")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
