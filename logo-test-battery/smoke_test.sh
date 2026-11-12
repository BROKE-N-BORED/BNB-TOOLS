#!/bin/bash
# Smoke test for T8 logo-test-battery.
# Generate a sample mark with the tool, run the battery, check outputs.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 logobattery.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

if ! python3 -c "import PIL" 2>/dev/null; then
  echo "Pillow NOT installed — logobattery requires it; smoke test cannot run"
  echo "T8 SMOKE TEST SKIPPED (missing Pillow)"
  exit 0
fi

python3 logobattery.py --make-sample "$WORK/mark.png" \
  || { echo "SMOKE FAIL: --make-sample"; exit 1; }
test -f "$WORK/mark.png" || { echo "SMOKE FAIL: no sample mark"; exit 1; }

python3 logobattery.py "$WORK/mark.png" --out "$WORK/out" \
  || { echo "SMOKE FAIL: battery run (a test failed — see report)"; exit 1; }

for f in report.md size-16px.png size-32px.png size-48px.png silhouette.png \
         grayscale.png invert-on-dark.png crop-circle.png crop-squircle.png \
         pasted-in-screenshot.png; do
  test -f "$WORK/out/$f" || { echo "SMOKE FAIL: missing output $f"; exit 1; }
done
grep -q "9/9 passed" "$WORK/out/report.md" \
  || { echo "SMOKE FAIL: report does not show 9/9"; exit 1; }
echo "T8 SMOKE TEST PASSED"
