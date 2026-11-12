#!/bin/bash
# Smoke test for T3 post-merge-battery-runner.
# Dummy unittest suite + known baseline: clean run, then a new failure.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/tree/tests"
cat > "$WORK/tree/tests/test_dummy.py" <<'EOF'
import unittest

class DummyTests(unittest.TestCase):
    def test_passes(self):
        self.assertEqual(1 + 1, 2)

    def test_known_failure(self):
        # Pre-existing failure, recorded in the baseline.
        self.assertEqual(1, 2, "known broken")

    def test_new_failure(self):
        # Passes in the clean run; the smoke test flips it to fail.
        import os
        self.assertTrue(os.environ.get("BREAK_IT") != "1", "newly broken")
EOF

# Baseline: the known failure only (unittest id format).
cat > "$WORK/baseline.txt" <<'EOF'
test_dummy.DummyTests.test_known_failure
EOF

python3 battery.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

# Run 1: clean — failure set must equal the baseline (exit 0).
# --skip-wait keeps the smoke test fast; the stability wait is
# exercised separately below with a short window.
cd "$WORK/tree"
python3 "$OLDPWD/battery.py" --tree "$WORK/tree" --skip-wait \
  --baseline "$WORK/baseline.txt" --log "$WORK/run1.log" \
  -- python3 -m unittest discover -s tests -v \
  || { echo "SMOKE FAIL: clean run should exit 0"; exit 1; }
grep -q "VERDICT: CLEAN" "$WORK/run1.log" 2>/dev/null || true
echo "clean run OK (failure set identical to baseline)"

# Run 2: flip the new test to failing — must exit 1 and name it.
BREAK_IT=1 python3 "$OLDPWD/battery.py" --tree "$WORK/tree" --skip-wait \
  --baseline "$WORK/baseline.txt" --log "$WORK/run2.log" \
  -- python3 -m unittest discover -s tests -v \
  && { echo "SMOKE FAIL: run with a new failure should exit 1"; exit 1; }
if grep -q "test_new_failure" "$WORK/run2.log"; then
  echo "new-failure flagging OK"
else
  echo "SMOKE FAIL: new failure not in log"; exit 1
fi

# Stability wait: tree is quiet, so a 2s window must clear quickly.
START=$(date +%s)
python3 "$OLDPWD/battery.py" --tree "$WORK/tree" --stable-seconds 2 \
  --poll-seconds 1 --max-wait-seconds 30 --skip-wait \
  --baseline "$WORK/baseline.txt" \
  -- python3 -c "print('battery ran')" >/dev/null \
  || { echo "SMOKE FAIL: stability-wait run"; exit 1; }
# Real wait (no --skip-wait): 2s quiet window on an untouched tree.
python3 "$OLDPWD/battery.py" --tree "$WORK/tree" --stable-seconds 2 \
  --poll-seconds 1 --max-wait-seconds 30 \
  --baseline "$WORK/baseline.txt" \
  -- python3 -c "print('battery ran')" \
  | grep -q "window clear" || { echo "SMOKE FAIL: window did not clear"; exit 1; }
echo "stability wait OK (window cleared on a quiet tree)"

echo "T3 SMOKE TEST PASSED"
