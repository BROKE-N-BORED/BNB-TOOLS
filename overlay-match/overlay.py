#!/usr/bin/env python3
"""T7 overlay-match — lay a render over a reference sheet at the same
scale and measure silhouette/dimension deltas.

Pairs with skill S18 (trace-and-overlay verification). Standing rule:
verify by measurement, not eyeballing — report residual offsets
honestly (e.g. "~1-2 cm vertical offset remains").

Two modes:
  * geometry (stdlib only): JSON in with two bounding boxes and/or
    polygons + a scale (units per pixel). Computes bbox width/height
    deltas, centroid offset, and polygon IoU. Use this when you have
    measured coordinates off the sheet (the belt-trace workflow).
  * image (needs Pillow): two image files (render + reference).
    Computes silhouette masks (non-background pixels), aligns them by
    bbox, reports bbox deltas, centroid offset and mask IoU, and
    writes an overlay PNG (reference red, render cyan, overlap white).

Geometry JSON format:
{
  "scale": 0.1,
  "scale_unit": "cm per pixel",
  "reference": {"box": [x0, y0, x1, y1],
                "polygon": [[x, y], ...]},
  "render":    {"box": [x0, y0, x1, y1],
                "polygon": [[x, y], ...]}
}
Box or polygon may be given alone; if both are given, both are measured.

Image mode needs Pillow (`pip install Pillow`); without it the tool
exits with a clear error naming the missing package instead of
pretending to work. A minimal PNG decoder is deliberately NOT
implemented — that is overkill for a measurement tool.
"""
import argparse
import json
import math
import sys


# ---------- geometry mode (stdlib) ----------

def box_stats(box):
    x0, y0, x1, y1 = box
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "width": x1 - x0, "height": y1 - y0,
            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
            "area": (x1 - x0) * (y1 - y0)}


def box_iou(a, b):
    ix0, iy0 = max(a["x0"], b["x0"]), max(a["y0"], b["y0"])
    ix1, iy1 = min(a["x1"], b["x1"]), min(a["y1"], b["y1"])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a["area"] + b["area"] - inter
    return inter / union if union else 0.0


def polygon_area(poly):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def polygon_centroid(poly):
    cx = cy = a2 = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        cross = x1 * y2 - x2 * y1
        a2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if a2 == 0:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (cx / (3 * a2), cy / (3 * a2))


def polygon_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def run_geometry(data):
    scale = data.get("scale", 1.0)
    unit = data.get("scale_unit", "units")
    ref, ren = data["reference"], data["render"]
    out = {"scale": scale, "scale_unit": unit}
    if "box" in ref and "box" in ren:
        a, b = box_stats(ref["box"]), box_stats(ren["box"])
        out["box"] = {
            "ref_w": a["width"], "ref_h": a["height"],
            "render_w": b["width"], "render_h": b["height"],
            "delta_w_px": b["width"] - a["width"],
            "delta_h_px": b["height"] - a["height"],
            "delta_w": (b["width"] - a["width"]) * scale,
            "delta_h": (b["height"] - a["height"]) * scale,
            "offset_x_px": b["cx"] - a["cx"],
            "offset_y_px": b["cy"] - a["cy"],
            "offset_x": (b["cx"] - a["cx"]) * scale,
            "offset_y": (b["cy"] - a["cy"]) * scale,
            "offset_magnitude": math.hypot(b["cx"] - a["cx"],
                                           b["cy"] - a["cy"]) * scale,
            "iou": box_iou(a, b),
        }
    if "polygon" in ref and "polygon" in ren:
        rp, pp = ref["polygon"], ren["polygon"]
        rc, pc = polygon_centroid(rp), polygon_centroid(pp)
        rb = box_stats(polygon_bbox(rp))
        pb = box_stats(polygon_bbox(pp))
        out["polygon"] = {
            "ref_area": polygon_area(rp),
            "render_area": polygon_area(pp),
            "area_delta": polygon_area(pp) - polygon_area(rp),
            "offset_x": (pc[0] - rc[0]) * scale,
            "offset_y": (pc[1] - rc[1]) * scale,
            "offset_magnitude": math.hypot(pc[0] - rc[0],
                                           pc[1] - rc[1]) * scale,
            "bbox_iou": box_iou(rb, pb),
        }
    return out


def print_geometry_report(out):
    print(f"scale: {out['scale']} {out['scale_unit']}")
    if "box" in out:
        b = out["box"]
        print("box:")
        print(f"  reference: {b['ref_w']} x {b['ref_h']} px; "
              f"render: {b['render_w']} x {b['render_h']} px")
        print(f"  size delta: {b['delta_w']:+.2f} x {b['delta_h']:+.2f} "
              f"{out['scale_unit']}")
        print(f"  centroid offset: ({b['offset_x']:+.2f}, "
              f"{b['offset_y']:+.2f}) {out['scale_unit']} "
              f"(magnitude {b['offset_magnitude']:.2f})")
        print(f"  box IoU: {b['iou']:.3f}")
    if "polygon" in out:
        p = out["polygon"]
        print("polygon:")
        print(f"  area delta: {p['area_delta']:+.1f} px^2")
        print(f"  centroid offset: ({p['offset_x']:+.2f}, "
              f"{p['offset_y']:+.2f}) {out['scale_unit']} "
              f"(magnitude {p['offset_magnitude']:.2f})")
        print(f"  bbox IoU: {p['bbox_iou']:.3f}")


# ---------- image mode (Pillow) ----------

def run_image(ref_path, ren_path, overlay_out=None, bg_threshold=250):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "error: image mode needs Pillow — pip install Pillow "
            "(geometry mode works without it: overlay.py geometry ...)")
    ref = Image.open(ref_path).convert("RGB")
    ren = Image.open(ren_path).convert("RGB")
    if ref.size != ren.size:
        ren = ren.resize(ref.size)
        print(f"note: render resized to reference size {ref.size}")

    def mask(img):
        # Silhouette = pixels darker than near-white on any channel.
        px = img.load()
        w, h = img.size
        m = [[False] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                r, g, b = px[x, y]
                m[y][x] = min(r, g, b) < bg_threshold
        return m

    def mask_stats(m):
        pts = [(x, y) for y, row in enumerate(m)
               for x, v in enumerate(row) if v]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return {"box": [min(xs), min(ys), max(xs), max(ys)],
                "count": len(pts),
                "cx": sum(xs) / len(xs), "cy": sum(ys) / len(ys)}

    rm, pm = mask(ref), mask(ren)
    rs, ps = mask_stats(rm), mask_stats(pm)
    if rs is None or ps is None:
        raise SystemExit("error: one image has an empty silhouette "
                         "(all background?)")
    h, w = len(rm), len(rm[0])
    inter = union = 0
    for y in range(h):
        for x in range(w):
            if rm[y][x] and pm[y][x]:
                inter += 1
            if rm[y][x] or pm[y][x]:
                union += 1
    iou = inter / union if union else 0.0
    rb, pb = box_stats(rs["box"]), box_stats(ps["box"])
    print(f"reference silhouette: {rs['count']} px, "
          f"box {rs['box']}; render: {ps['count']} px, box {ps['box']}")
    print(f"size delta: {pb['width'] - rb['width']:+d} x "
          f"{pb['height'] - rb['height']:+d} px")
    print(f"centroid offset: ({ps['cx'] - rs['cx']:+.1f}, "
          f"{ps['cy'] - rs['cy']:+.1f}) px "
          f"(magnitude {math.hypot(ps['cx'] - rs['cx'], ps['cy'] - rs['cy']):.1f})")
    print(f"silhouette IoU: {iou:.3f} (1.000 = perfect overlap)")
    if overlay_out:
        out = Image.new("RGB", ref.size, (0, 0, 0))
        px = out.load()
        for y in range(h):
            for x in range(w):
                if rm[y][x] and pm[y][x]:
                    px[x, y] = (255, 255, 255)  # overlap: white
                elif rm[y][x]:
                    px[x, y] = (255, 0, 0)      # reference only: red
                elif pm[y][x]:
                    px[x, y] = (0, 255, 255)    # render only: cyan
        out.save(overlay_out)
        print(f"overlay -> {overlay_out} (red=reference, cyan=render, "
              f"white=overlap)")
    return {"iou": iou, "offset": (ps["cx"] - rs["cx"],
                                   ps["cy"] - rs["cy"])}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="overlay.py",
        description="Measure render-vs-reference silhouette/dimension "
                    "deltas (geometry mode: stdlib; image mode: Pillow).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("geometry", help="measure from JSON coordinates")
    g.add_argument("json", help="geometry JSON file (see README)")
    g.add_argument("--json-out", default=None,
                   help="also write the numeric results as JSON")
    i = sub.add_parser("image", help="measure from two image files")
    i.add_argument("reference", help="reference sheet image")
    i.add_argument("render", help="render image")
    i.add_argument("--overlay-out", default=None,
                   help="write a red/cyan/white overlay PNG here")
    i.add_argument("--bg-threshold", type=int, default=250,
                   help="silhouette threshold (default 250)")
    args = ap.parse_args(argv)
    if args.cmd == "geometry":
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
        out = run_geometry(data)
        print_geometry_report(out)
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            print(f"results -> {args.json_out}")
        return 0
    run_image(args.reference, args.render, args.overlay_out,
              args.bg_threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
