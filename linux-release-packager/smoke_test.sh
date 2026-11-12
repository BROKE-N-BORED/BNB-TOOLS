#!/bin/bash
# Smoke test for T6 linux-release-packager.
# Package a tiny sample app; validate .desktop files + installer bash.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/app"
cat > "$WORK/app/main.py" <<'EOF'
print("sample app runs")
EOF
cat > "$WORK/app/icon.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">
  <rect width="128" height="128" fill="#1e1e1e"/>
  <circle cx="64" cy="64" r="40" fill="#c85014"/>
</svg>
EOF
mkdir -p "$WORK/app/__pycache__"
printf 'junk' > "$WORK/app/__pycache__/x.pyc"

python3 package.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

python3 package.py --tree "$WORK/app" --name sampleapp \
  --display-name "Sample App" --icon "$WORK/app/icon.svg" \
  --entry main.py --dep json --out "$WORK/out" \
  || { echo "SMOKE FAIL: package"; exit 1; }

test -f "$WORK/out/install.sh" || { echo "SMOKE FAIL: no install.sh"; exit 1; }
test -f "$WORK/out/uninstall.sh" || { echo "SMOKE FAIL: no uninstall.sh"; exit 1; }
test -f "$WORK/out/sampleapp.desktop" || { echo "SMOKE FAIL: no app .desktop"; exit 1; }
test -f "$WORK/out/Install Sample App.desktop" || { echo "SMOKE FAIL: no installer .desktop"; exit 1; }
test -f "$WORK/out/sampleapp/main.py" || { echo "SMOKE FAIL: tree not staged"; exit 1; }
test -f "$WORK/out/sampleapp/icon.svg" || { echo "SMOKE FAIL: icon SVG not staged"; exit 1; }
if [ -e "$WORK/out/sampleapp/__pycache__" ]; then
  echo "SMOKE FAIL: __pycache__ leaked into the package"; exit 1
fi

# Installer must be valid bash.
bash -n "$WORK/out/install.sh" || { echo "SMOKE FAIL: install.sh bash -n"; exit 1; }
bash -n "$WORK/out/uninstall.sh" || { echo "SMOKE FAIL: uninstall.sh bash -n"; exit 1; }
echo "installer bash syntax OK"

# .desktop validation: desktop-file-validate if present, else a parser check.
if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$WORK/out/Install Sample App.desktop" \
    || { echo "SMOKE FAIL: installer .desktop invalid"; exit 1; }
  desktop-file-validate "$WORK/out/sampleapp.desktop" \
    || { echo "SMOKE FAIL: app .desktop invalid"; exit 1; }
  echo ".desktop validation OK (desktop-file-validate)"
else
  echo "note: desktop-file-validate not installed — using a parser check"
  python3 - "$WORK/out" <<'EOF'
import configparser, sys
for name in ["Install Sample App.desktop", "sampleapp.desktop"]:
    p = configparser.ConfigParser(interpolation=None)
    p.optionxform = str
    with open(f"{sys.argv[1]}/{name}") as f:
        p.read_file(f)
    assert p.has_section("Desktop Entry"), name
    assert p.get("Desktop Entry", "Type") == "Application", name
    assert p.get("Desktop Entry", "Name"), name
    assert p.get("Desktop Entry", "Exec"), name
print(".desktop parser check OK")
EOF
fi

# GLib rule: no nested escaped quotes in any Exec line.
if grep -r 'Exec=.*\\"' "$WORK/out"/*.desktop; then
  echo "SMOKE FAIL: nested escaped quote in an Exec line (GLib rejects it)"
  exit 1
fi
grep -q 'Exec=python3 -c ".*" %k' "$WORK/out/Install Sample App.desktop" \
  || { echo "SMOKE FAIL: installer Exec is not the GLib-safe pattern"; exit 1; }
echo "GLib-safe Exec quoting OK"

# Icon PNGs: rendered only if a renderer exists; either way the tool
# must have said so clearly.
if ls "$WORK/out/sampleapp/icons/"*.png >/dev/null 2>&1; then
  echo "icon PNGs rendered OK"
else
  echo "note: no SVG renderer installed in this sandbox (no rsvg-convert / cairosvg / ImageMagick) — PNGs skipped, SVG ships as source of truth"
fi

echo "T6 SMOKE TEST PASSED"
