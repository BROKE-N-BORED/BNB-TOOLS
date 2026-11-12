#!/bin/bash
# Smoke test for T5 model-sweep-harness.
# Run on the sample file; check the table + over-ceiling flag.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 sweep.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

python3 sweep.py candidates.sample.json --out "$WORK/report.md" \
  || { echo "SMOKE FAIL: sweep run"; exit 1; }

grep -q "OVER" "$WORK/report.md" \
  || { echo "SMOKE FAIL: over-ceiling flag missing"; exit 1; }
grep -q "big-model-example" "$WORK/report.md" \
  || { echo "SMOKE FAIL: over-ceiling model missing from table"; exit 1; }
grep -q "UNREPRODUCED" "$WORK/report.md" \
  || { echo "SMOKE FAIL: vendor-benchmark flag missing"; exit 1; }
grep -q "ollama pull qwen3-vl:2b-instruct" "$WORK/report.md" \
  || { echo "SMOKE FAIL: trial list missing exact pull tag"; exit 1; }
# Over-ceiling model must be in the rejects section, not the trial list.
if awk '/## Ranked trial list/{f=1} /## Rejects/{f=0} f' "$WORK/report.md" \
   | grep -q "big-model-example"; then
  echo "SMOKE FAIL: over-ceiling model in trial list"; exit 1
fi
grep -q "no-runtime-example" "$WORK/report.md" \
  || { echo "SMOKE FAIL: no-runtime model missing"; exit 1; }
echo "T5 SMOKE TEST PASSED"
