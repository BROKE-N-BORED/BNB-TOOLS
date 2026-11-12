#!/bin/bash
# Smoke test for T9 brand-scrub-rename.
# Dry-run + apply on a sample tree; verify counts + clean straggler grep.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/tree/sub" "$WORK/tree/.git" "$WORK/tree/__pycache__"
cat > "$WORK/tree/app.py" <<'EOF'
# Goldfish app
NAME = "Goldfish"
print("Goldfish running")
EOF
cat > "$WORK/tree/sub/doc.md" <<'EOF'
# Goldfish
The Goldfish project. goldfish in lowercase too.
EOF
printf 'Goldfish should be ignored here\n' > "$WORK/tree/.git/config"
printf 'Goldfish should be ignored here\n' > "$WORK/tree/__pycache__/x.py"

cat > "$WORK/key-renames.json" <<'EOF'
{"goldfish_plan": "gofish_plan", "goldfish_enabled": "gofish_enabled"}
EOF

python3 scrub.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

# Dry run: 5 occurrences in 2 files (3 in app.py, 2 in doc.md — the
# lowercase "goldfish" does NOT match the case-sensitive default).
OUT=$(python3 scrub.py Goldfish GoFish --tree "$WORK/tree")
echo "$OUT"
echo "$OUT" | grep -q "5 occurrence(s) in 2 file(s)" \
  || { echo "SMOKE FAIL: dry-run counts wrong"; exit 1; }
grep -q "Goldfish" "$WORK/tree/app.py" \
  || { echo "SMOKE FAIL: dry run changed a file"; exit 1; }
echo "dry-run counts OK (5 in 2 files), nothing changed"

# Apply: straggler grep must FAIL because the lowercase "goldfish" in
# doc.md survives a case-sensitive replace — that is the straggler
# catch working as designed. Re-run with --ignore-case to finish.
if python3 scrub.py Goldfish GoFish --tree "$WORK/tree" --apply; then
  echo "SMOKE FAIL: straggler grep should have caught the lowercase hit"
  exit 1
else
  echo "straggler catch OK (lowercase 'goldfish' flagged)"
fi
python3 scrub.py Goldfish GoFish --tree "$WORK/tree" --apply --ignore-case \
  --key-renames "$WORK/key-renames.json" \
  --mapping-out "$WORK/key-mapping.json" \
  --migration-out "$WORK/migrate.py" \
  || { echo "SMOKE FAIL: --ignore-case apply"; exit 1; }
if grep -ri "goldfish" "$WORK/tree/app.py" "$WORK/tree/sub/doc.md"; then
  echo "SMOKE FAIL: occurrences remain after --ignore-case apply"; exit 1
fi
echo "apply + clean straggler grep OK"

# Excluded dirs must be untouched.
grep -q "Goldfish" "$WORK/tree/.git/config" \
  || { echo "SMOKE FAIL: .git was scrubbed"; exit 1; }
grep -q "Goldfish" "$WORK/tree/__pycache__/x.py" \
  || { echo "SMOKE FAIL: __pycache__ was scrubbed"; exit 1; }
echo "excludes OK (.git and __pycache__ untouched)"

# Migration scaffolding: mapping + snippet that actually renames keys.
test -f "$WORK/key-mapping.json" || { echo "SMOKE FAIL: no mapping"; exit 1; }
test -f "$WORK/migrate.py" || { echo "SMOKE FAIL: no migrate.py"; exit 1; }
python3 - "$WORK" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from migrate import migrate_state
state = {"goldfish_plan": "p1", "goldfish_enabled": True, "other": 1}
out = migrate_state(state)
assert out == {"gofish_plan": "p1", "gofish_enabled": True, "other": 1}, out
print("migration snippet OK (keys renamed, others untouched)")
EOF

echo "T9 SMOKE TEST PASSED"
