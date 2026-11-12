#!/usr/bin/env python3
"""T8 logo-test-battery — run a mark through the S21 test battery and
report pass/fail per test.

Pairs with skill S21 (brand-matched logo / glyph design, anti-slop).
The skill's 12-test battery includes subjective checks (competitor
wall, letterform audit, grid audit) that need human eyes — this tool
automates the 8 renderable ones:

  1-3. legibility at 16/32/48 px (ink fraction must stay in range)
  4.   solid-black silhouette
  5.   grayscale
  6.   invert (on dark)
  7.   circle crop + squircle crop
  8.   pasted into a real product screenshot (or a generated stand-in)

Every test produces an output image + a PASS/FAIL line in the report.
A test FAILS only on a measured defect (mark vanishes at small size,
silhouette is a blob, crop cuts the mark, paste is invisible) — the
report states the measured number, not a vibe.

Input: PNG (or JPG) via Pillow. SVG input is supported when
rsvg-convert or cairosvg is available; otherwise the tool errors
clearly and asks for a PNG render. Pillow is REQUIRED for this tool
(`pip install Pillow`).

`--make-sample` generates a tiny sample mark (a forge-anvil-ish
geometric glyph drawn in code — no image generation for marks, per
the S21 anti-slop rule) so the battery can be smoke-tested with no
input at all.
"""
import argparse
import os
import shutil
import subprocess
import sys

SIZES = [16, 32, 48]
# A mark that keeps less than 2% ink at 16px has effectively vanished;
# more than 95% ink at any size is a blob, not a mark.
INK_MIN = 0.02
INK_MAX = 0.95


def need_pillow():
    try:
        from PIL import Image, ImageDraw, ImageOps  # noqa: F401
        return Image, ImageDraw, ImageOps
    except ImportError:
        raise SystemExit(
            "error: logo-test-battery needs Pillow — pip install Pillow")


def load_mark(path):
    Image, _, _ = need_pillow()
    if path.lower().endswith(".svg"):
        png = path + ".rendered.png"
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-w", "512", "-h", "512",
                            "-o", png, path], check=True)
        else:
            try:
                import cairosvg  # noqa: F401
                subprocess.run([sys.executable, "-m", "cairosvg", path,
                                "-o", png, "-W", "512", "-H", "512"],
                               check=True)
            except ImportError:
                raise SystemExit(
                    "error: SVG input needs rsvg-convert or cairosvg — "
                    "neither is installed. Render the mark to PNG first "
                    "or install one of them.")
        path = png
    img = Image.open(path).convert("RGBA")
    return img


def ink_fraction(img):
    """Fraction of the WHOLE canvas covered by visible mark pixels.

    Transparent pixels count as background, not as canvas: an RGBA
    mark is composited over white first, then ink = pixels darker
    than near-white. (Measuring only over opaque pixels made every
    mark read 1.000 — a mark with no background is not a blob.)
    """
    Image, _, _ = need_pillow()
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, (0, 0), img)
        img = bg
    rgb = img.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    ink = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if min(r, g, b) < 240:
                ink += 1
    return ink / (w * h)


def light_fraction(img):
    """Fraction of pixels visibly light (for marks on a dark ground)."""
    rgb = img.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    lit = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) > 60:
                lit += 1
    return lit / (w * h)


def make_sample_mark(path, size=512):
    """Draw a small geometric mark in code (no image generation)."""
    Image, ImageDraw, _ = need_pillow()
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size // 2
    # Anvil-ish glyph: body + horn + base, in one flat colour.
    d.polygon([(c - 140, c - 60), (c + 180, c - 60), (c + 60, c + 10),
               (c - 140, c + 10)], fill=(30, 30, 30, 255))
    d.rectangle([c - 40, c + 10, c + 40, c + 90], fill=(30, 30, 30, 255))
    d.rectangle([c - 110, c + 90, c + 110, c + 130],
                fill=(30, 30, 30, 255))
    d.ellipse([c - 200, c - 200, c + 200, c + 200], outline=(200, 80, 20, 255),
              width=18)
    img.save(path)
    return path


def make_sample_screenshot(path, size=(800, 500)):
    """A stand-in product screenshot (dark app window) for the paste test."""
    Image, ImageDraw, _ = need_pillow()
    img = Image.new("RGB", size, (24, 24, 28))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size[0], 44], fill=(40, 40, 48))
    d.rectangle([16, 60, 200, size[1] - 16], fill=(36, 36, 42))
    d.rectangle([216, 60, size[0] - 16, size[1] - 16], fill=(30, 30, 36))
    d.rectangle([24, 70, 192, 90], fill=(70, 70, 80))
    d.rectangle([24, 100, 192, 120], fill=(70, 70, 80))
    img.save(path)
    return path


def squircle_mask(size, radius_frac=0.28):
    """Approximate a squircle (superellipse n=4) as an L-mode mask."""
    Image, ImageDraw, _ = need_pillow()
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    # Superellipse sampled as a polygon.
    import math
    n = 4
    pts = []
    cx = cy = size / 2
    r = size / 2
    for i in range(97):
        t = 2 * math.pi * i / 96
        ct, st = math.cos(t), math.sin(t)
        x = cx + r * (abs(ct) ** (2 / n)) * (1 if ct >= 0 else -1)
        y = cy + r * (abs(st) ** (2 / n)) * (1 if st >= 0 else -1)
        pts.append((x, y))
    d.polygon(pts, fill=255)
    return mask


def run_battery(mark_path, screenshot_path, out_dir):
    Image, ImageDraw, ImageOps = need_pillow()
    os.makedirs(out_dir, exist_ok=True)
    mark = load_mark(mark_path)
    results = []  # (name, passed, detail, output_file)

    def record(name, passed, detail, outfile):
        results.append((name, passed, detail, outfile))
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    # 1-3. Small-size renders.
    for size in SIZES:
        small = mark.resize((size, size), Image.LANCZOS)
        out = os.path.join(out_dir, f"size-{size}px.png")
        small.save(out)
        ink = ink_fraction(small)
        record(f"legibility {size}px", INK_MIN <= ink <= INK_MAX,
               f"ink fraction {ink:.3f} (range {INK_MIN}-{INK_MAX})", out)
    # 4. Silhouette (solid black on white).
    alpha = mark.split()[3] if mark.mode == "RGBA" else None
    sil = Image.new("RGBA", mark.size, (255, 255, 255, 255))
    black = Image.new("RGBA", mark.size, (0, 0, 0, 255))
    sil.paste(black, (0, 0), alpha if alpha else mark.convert("L"))
    out = os.path.join(out_dir, "silhouette.png")
    sil.convert("RGB").save(out)
    ink = ink_fraction(sil.convert("RGB"))
    record("silhouette", INK_MIN <= ink <= INK_MAX,
           f"ink fraction {ink:.3f}", out)
    # 5. Grayscale (composite over white first — a raw RGBA->L convert
    #    turns transparent pixels black and the test reads 1.000).
    white_bg = Image.new("RGB", mark.size, (255, 255, 255))
    if mark.mode == "RGBA":
        white_bg.paste(mark, (0, 0), mark)
        gray_src = white_bg
    else:
        gray_src = mark.convert("RGB")
    out = os.path.join(out_dir, "grayscale.png")
    gray_src.convert("L").convert("RGB").save(out)
    ink = ink_fraction(gray_src.convert("L"))
    record("grayscale", INK_MIN <= ink <= INK_MAX,
           f"ink fraction {ink:.3f}", out)
    # 6. Invert on dark: invert the MARK's colours only, keep the ground
    #    dark, and measure the light fraction (a mark that inverts to
    #    near-black on dark is invisible).
    inv_mark = ImageOps.invert(mark.convert("RGB"))
    dark = Image.new("RGB", mark.size, (0, 0, 0))
    alpha = mark.split()[3] if mark.mode == "RGBA" else None
    dark.paste(inv_mark, (0, 0), alpha)
    out = os.path.join(out_dir, "invert-on-dark.png")
    dark.save(out)
    lit = light_fraction(dark)
    record("invert", INK_MIN <= lit <= INK_MAX,
           f"light fraction {lit:.3f}", out)
    # 7a. Circle crop.
    circ = Image.new("RGBA", mark.size, (0, 0, 0, 0))
    mask = Image.new("L", mark.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, mark.size[0], mark.size[1]],
                                 fill=255)
    circ.paste(mark, (0, 0), mask)
    out = os.path.join(out_dir, "crop-circle.png")
    circ.save(out)
    ink = ink_fraction(circ)
    record("circle crop", ink >= INK_MIN,
           f"ink fraction after crop {ink:.3f}", out)
    # 7b. Squircle crop.
    sq = Image.new("RGBA", mark.size, (0, 0, 0, 0))
    sq.paste(mark, (0, 0), squircle_mask(mark.size[0]))
    out = os.path.join(out_dir, "crop-squircle.png")
    sq.save(out)
    ink = ink_fraction(sq)
    record("squircle crop", ink >= INK_MIN,
           f"ink fraction after crop {ink:.3f}", out)
    # 8. Paste into a product screenshot.
    shot_path = screenshot_path or os.path.join(out_dir,
                                                "screenshot-standin.png")
    if not screenshot_path:
        make_sample_screenshot(shot_path)
        print("note: no screenshot given — used a generated stand-in "
              "(paste test is weaker; supply a real screenshot with "
              "--screenshot for the real check)")
    shot = Image.open(shot_path).convert("RGB")
    paste = mark.resize((96, 96), Image.LANCZOS)
    before = shot.crop((24, 60, 120, 156))
    shot.paste(paste, (24, 60), paste if paste.mode == "RGBA" else None)
    out = os.path.join(out_dir, "pasted-in-screenshot.png")
    shot.save(out)
    # Visibility = fraction of pixels the paste actually changed (the
    # screenshot ground is dark, so an ink fraction would read ~1.0
    # even with no mark at all).
    after = shot.crop((24, 60, 120, 156))
    bp, ap = before.load(), after.load()
    changed = 0
    for y in range(96):
        for x in range(96):
            if bp[x, y] != ap[x, y]:
                changed += 1
    frac = changed / (96 * 96)
    record("paste in screenshot", frac >= INK_MIN,
           f"mark changed {frac:.3f} of the pasted region", out)

    report = os.path.join(out_dir, "report.md")
    passed = sum(1 for r in results if r[1])
    with open(report, "w", encoding="utf-8") as f:
        f.write("# Logo test battery — report\n\n")
        f.write(f"Mark: `{mark_path}`\n\n")
        f.write(f"Result: **{passed}/{len(results)} passed**\n\n")
        f.write("| Test | Result | Detail | Output |\n")
        f.write("|---|---|---|---|\n")
        for name, ok, detail, outfile in results:
            f.write(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} | "
                    f"`{os.path.basename(outfile)}` |\n")
        f.write("\nSubjective checks NOT covered here (need human eyes): "
                "competitor wall, letterform audit, grid audit.\n")
    print(f"report -> {report}")
    print(f"battery: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="logobattery.py",
        description="Run a mark through the renderable S21 logo tests.")
    ap.add_argument("mark", nargs="?", default=None,
                    help="mark image (PNG/JPG, or SVG with rsvg/cairosvg)")
    ap.add_argument("--screenshot", default=None,
                    help="real product screenshot for the paste test")
    ap.add_argument("--out", default="logo-battery-out",
                    help="output directory (default logo-battery-out)")
    ap.add_argument("--make-sample", default=None, metavar="PATH",
                    help="generate a sample mark at PATH and exit")
    args = ap.parse_args(argv)
    if args.make_sample:
        make_sample_mark(args.make_sample)
        print(f"sample mark -> {args.make_sample}")
        return 0
    if not args.mark:
        ap.error("no mark given (or use --make-sample to generate one)")
    return run_battery(args.mark, args.screenshot, args.out)


if __name__ == "__main__":
    sys.exit(main())
