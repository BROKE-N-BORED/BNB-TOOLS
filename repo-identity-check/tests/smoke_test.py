#!/usr/bin/env python3
"""Smoke test for T10 repo-identity-check.

Live checks (needs network): a well-known repo, a gibberish name, and the
description heuristic. Offline unit checks for the keyword-overlap function
run regardless.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "repo_identity.py"
sys.path.insert(0, str(HERE.parent))
import repo_identity  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, timeout=60)
    return p


def main():
    fails = []
    # 1. --help
    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    # 2. well-known repo, live
    p = run("torvalds/linux")
    print("== torvalds/linux exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0:
        fails.append("live check of torvalds/linux failed: %s" % p.stderr)
    elif "exists:      YES" not in p.stdout or "empty:       NO" not in p.stdout:
        fails.append("torvalds/linux should exist and be non-empty")

    # 3. gibberish name, live — must report NO, not an error
    p = run("zzzqqqx-no-such-owner-zzz/zzzqqqx-no-such-repo-zzz")
    print("== gibberish exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0:
        fails.append("gibberish check should exit 0: %s" % p.stderr)
    elif "exists:      NO" not in p.stdout:
        fails.append("gibberish repo should report exists: NO")

    # 4. description heuristic, offline unit check
    fake = {"repo": "x/StemLab", "description": "stem separation trainer",
            "readme": {"first_lines": ["StemLab: separate stems"]}}
    score, shared, verdict = repo_identity.match_verdict(
        fake, "a stem separation trainer for music")
    print("== heuristic score=%.2f shared=%s" % (score, shared))
    print("   %s" % verdict)
    if score < 0.5 or "stem" not in shared:
        fails.append("heuristic should match 'stem separation trainer'")

    # 5. 404 handling unit check: api_get on a missing repo returns (404, None)
    try:
        status, data = repo_identity.api_get(
            "/repos/zzzqqqx-no-such-owner-zzz/zzzqqqx-no-such-repo-zzz")
        print("== api_get missing repo -> status=%s data=%s" % (status, data))
        if status != 404 or data is not None:
            fails.append("missing repo must return (404, None), got (%r, %r)"
                         % (status, data))
    except repo_identity.CouldNotCheck as e:
        fails.append("api_get raised instead of returning 404: %s" % e)

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
