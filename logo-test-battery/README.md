# T8 — logo-test-battery

Pairs with skill **S21** (brand-matched logo / glyph design, anti-slop).

Runs a mark through the renderable half of the S21 12-test battery and reports pass/fail per test. The subjective checks (competitor wall, letterform audit, grid audit) still need human eyes and are listed as not covered in the report.

## What it does

Each test produces an output image + a PASS/FAIL line in `report.md`, with the measured number stated (a test fails only on a measured defect — the mark vanishing at small size, a silhouette that is a blob, a crop cutting the mark, an invisible paste):

1–3. Legibility at 16/32/48 px (ink fraction must stay in 0.02–0.95)
4. Solid-black silhouette
5. Grayscale
6. Invert (on dark)
7. Circle crop + squircle crop
8. Pasted into a real product screenshot (`--screenshot`; without one, a generated stand-in window is used and the report says so)

`--make-sample` generates a tiny sample mark drawn in code, so the battery can be smoke-tested with no input. No image generation for marks, per the S21 anti-slop rule.

## Requirements

- Pillow (`pip install Pillow`) — **required**.
- SVG input needs `rsvg-convert` or `cairosvg`; otherwise pass a PNG render of the mark.

## Usage

```bash
# Generate a sample mark, then run the battery on it
python3 logobattery.py --make-sample sample-mark.png
python3 logobattery.py sample-mark.png --out battery-out

# With a real product screenshot for the paste test
python3 logobattery.py mark.png --screenshot app-window.png --out battery-out
```

Exit code 0 only if every test passes.

## Smoke test

```bash
bash smoke_test.sh
```

Generates a sample mark with the tool itself, runs the battery, and verifies the report + output images exist.
