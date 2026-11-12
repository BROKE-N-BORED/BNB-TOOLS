#!/bin/bash
# Smoke test for T7 overlay-match.
# Geometry mode on the sample coordinates; image mode if Pillow exists.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 overlay.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

# Geometry mode (stdlib): the sample has the render 1.4 cm lower and
# 0.2 cm narrower/shorter than the reference at 0.1 cm/px.
python3 overlay.py geometry geometry.sample.json \
  --json-out "$WORK/results.json" || { echo "SMOKE FAIL: geometry mode"; exit 1; }
python3 - "$WORK/results.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
b = d["box"]
# Sample: ref box 84x70, render box 82x68 shifted +2x/+15y px.
assert abs(b["offset_x"] - 0.1) < 0.01, b  # +1 px centroid x * 0.1
assert abs(b["offset_y"] - 1.4) < 0.01, b  # +14 px centroid y * 0.1
assert b["iou"] > 0.6, b
print(f"geometry mode OK: offset ({b['offset_x']:+.2f}, {b['offset_y']:+.2f}) cm, IoU {b['iou']:.3f}")
EOF

# Image mode: only if Pillow is present; report which path ran.
if python3 -c "import PIL" 2>/dev/null; then
  echo "Pillow present — running image mode"
  python3 - "$WORK" <<'EOF'
import sys
from PIL import Image, ImageDraw
w = sys.argv[1]
ref = Image.new("RGB", (200, 200), (255, 255, 255))
ImageDraw.Draw(ref).rectangle([50, 50, 150, 120], fill=(0, 0, 0))
ref.save(f"{w}/ref.png")
ren = Image.new("RGB", (200, 200), (255, 255, 255))
ImageDraw.Draw(ren).rectangle([55, 65, 155, 135], fill=(0, 0, 0))
ren.save(f"{w}/ren.png")
EOF
  python3 overlay.py image "$WORK/ref.png" "$WORK/ren.png" \
    --overlay-out "$WORK/overlay.png" \
    || { echo "SMOKE FAIL: image mode"; exit 1; }
  test -f "$WORK/overlay.png" || { echo "SMOKE FAIL: no overlay PNG"; exit 1; }
  echo "image mode OK (Pillow path)"
else
  echo "Pillow NOT installed — image mode skipped (geometry mode ran)"
  if python3 overlay.py image a.png b.png 2>&1 | grep -qi "Pillow"; then
    echo "image mode correctly errors naming Pillow when it is missing"
  else
    echo "SMOKE FAIL: image mode did not name Pillow in its error"; exit 1
  fi
fi

echo "T7 SMOKE TEST PASSED"
