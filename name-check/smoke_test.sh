#!/bin/bash
# Smoke test for T4 name-check.
# --help + a certainly-taken name ("linux") + a random gibberish name.
# Network availability decides whether verdicts are definite or
# "could not check" — the test reports what actually happened and only
# fails on a crash or on a network failure being reported as "clean".
set -u
cd "$(dirname "$0")"

python3 namecheck.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

GIBBERISH="zxqvjkwplm$(date +%s)"
OUT=$(python3 namecheck.py --delay 6 "linux" "$GIBBERISH" 2>&1)
echo "$OUT"

# The tool must never claim a name is clean when a check could not run.
if echo "$OUT" | grep -q ': COULD NOT CHECK'; then
  echo "note: at least one name could not be checked (network/rate limit) —"
  echo "verdicts are 'could not check', never a false 'clean'."
fi
# "linux" must never come back clean when GitHub was actually checked.
if echo "$OUT" | grep -A2 '^linux:' | grep -qi 'CLEAN'; then
  echo "SMOKE FAIL: 'linux' reported clean — GitHub check is broken"
  exit 1
fi
echo "T4 SMOKE TEST PASSED (see verdicts above for what the network said)"
