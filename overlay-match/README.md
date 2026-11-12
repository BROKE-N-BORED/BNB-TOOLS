# T7 — overlay-match

Pairs with skill **S18** (trace-and-overlay verification). Standing rule: verify by measurement, not eyeballing — report residual offsets honestly.

## What it does

Lays a render over a reference sheet at the same scale and measures silhouette/dimension deltas.

**Geometry mode (stdlib only)** — JSON in with two bounding boxes and/or polygons + a scale. Computes bbox width/height deltas, centroid offset (in real units via the scale), and box/polygon IoU. This is the belt-trace workflow: dimensions measured off the sheet, compared numerically.

```json
{
  "scale": 0.1, "scale_unit": "cm per pixel",
  "reference": {"box": [x0, y0, x1, y1], "polygon": [[x, y], ...]},
  "render":    {"box": [x0, y0, x1, y1], "polygon": [[x, y], ...]}
}
```

Box or polygon may be given alone. See `geometry.sample.json`.

**Image mode (needs Pillow)** — two image files. Computes silhouette masks (non-background pixels), aligns by bbox, reports bbox deltas, centroid offset, and mask IoU, and writes an overlay PNG (reference red, render cyan, overlap white).

A minimal PNG decoder was deliberately **not** implemented — overkill for a measurement tool. Without Pillow, image mode exits with a clear error naming the missing package; geometry mode always works.

## Requirements

- Geometry mode: Python 3.8+, stdlib only.
- Image mode: Pillow (`pip install Pillow`).

## Usage

```bash
# Geometry mode
python3 overlay.py geometry geometry.sample.json --json-out results.json

# Image mode
python3 overlay.py image reference.png render.png --overlay-out overlay.png
```

## Smoke test

```bash
bash smoke_test.sh
```

Runs geometry mode on the sample coordinates; runs image mode only if Pillow is installed and reports which path ran.
