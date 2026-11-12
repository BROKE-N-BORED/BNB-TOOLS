#!/bin/bash
# Smoke test for T1 ship-pipeline-scripts.
# Packs a small sample tree, verifies stored modes, hash-matches a copy.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Sample tree: a script, a plain file, a .desktop, junk to exclude.
mkdir -p "$WORK/tree/sub" "$WORK/tree/__pycache__" "$WORK/tree/.forge"
printf '#!/bin/bash\necho hi\n' > "$WORK/tree/install.sh"
printf 'print("hello")\n' > "$WORK/tree/main.py"
printf '[Desktop Entry]\nName=X\n' > "$WORK/tree/app.desktop"
printf 'docs\n' > "$WORK/tree/sub/README.md"
printf 'junk' > "$WORK/tree/__pycache__/x.pyc"
printf 'junk' > "$WORK/tree/.forge/project.json"
printf 'junk' > "$WORK/tree/stale.pyc"

python3 ship.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

python3 ship.py build "$WORK/tree" "$WORK/out.zip" --top "Sample App" \
  || { echo "SMOKE FAIL: build"; exit 1; }

# Excludes must have worked: no __pycache__ / .forge / .pyc entries.
if python3 -c "import zipfile,sys; z=zipfile.ZipFile('$WORK/out.zip'); bad=[n for n in z.namelist() if '__pycache__' in n or '.forge' in n or n.endswith('.pyc')]; sys.exit(1 if bad else 0)"; then
  echo "excludes OK"
else
  echo "SMOKE FAIL: excluded paths present in zip"; exit 1
fi

# Stored modes must carry file-type bits (checked by verify + directly).
python3 ship.py verify "$WORK/out.zip" || { echo "SMOKE FAIL: verify"; exit 1; }
python3 - "$WORK/out.zip" <<'EOF'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
modes = {n: (i.external_attr >> 16) for n, i in
         ((i.filename, i) for i in z.infolist())}
assert modes["Sample App/install.sh"] == 0o100755, modes
assert modes["Sample App/app.desktop"] == 0o100755, modes
assert modes["Sample App/main.py"] == 0o100644, modes
assert modes["Sample App/sub/"] == 0o40755, modes
print("stored modes OK (0o100755 scripts / 0o100644 files / 0o40755 dirs)")
EOF

# Hash-match a copy, then prove compare detects a difference.
cp "$WORK/out.zip" "$WORK/copy.zip"
python3 ship.py compare "$WORK/out.zip" "$WORK/copy.zip" \
  || { echo "SMOKE FAIL: compare identical files"; exit 1; }
printf 'x' >> "$WORK/copy.zip"
if python3 ship.py compare "$WORK/out.zip" "$WORK/copy.zip"; then
  echo "SMOKE FAIL: compare missed a difference"; exit 1
else
  echo "compare mismatch detection OK"
fi

echo "T1 SMOKE TEST PASSED"
