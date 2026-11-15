#!/usr/bin/env python3
"""Photo Palette (BNB-TOOLS T35) - real colors sampled from photos.

Give it one or more photos and it samples pixels from them,
pulls out a palette of real colors, and prints a hex list plus
CSS variables. Every hex in the output is a color that was
actually sampled from the photos, never an average or a guess.

Method, honestly stated: each photo is sampled at evenly spaced
positions (no randomness, so the same photos always give the
same palette), the pooled samples are clustered with median-cut
(PIL quantize), and each cluster color is then snapped to the
nearest color that was actually sampled. The palette is ordered
most common first. See README.md for the full description.

Usage:
  python3 photo_palette.py photo.jpg
  python3 photo_palette.py one.jpg two.png --colors 12 --sample 30000
  python3 photo_palette.py photo.jpg --out palette.css
  python3 photo_palette.py --debug-report

Requirements: Python 3.8+ and Pillow (PIL). No network.
"""

import argparse
import os
import sys
from collections import Counter

VERSION = "0.1.0"
APP_NAME = "photo-palette"
DEFAULT_COLORS = 12
DEFAULT_SAMPLE = 30000
MAX_COLORS = 256

try:
    from PIL import Image
except ImportError:  # Pillow not installed: handled in main(), plainly
    Image = None


class PaletteError(Exception):
    """A problem the user can fix, in plain words."""


# ---------------------------------------------------------------- sampling

def sample_pixels(image, quota):
    """Evenly spaced pixels from one image, at most quota of them.

    Deterministic: positions are spread evenly across the whole
    image by flat index, no random numbers anywhere, so the same
    image always gives the same samples. A small image gives all
    its pixels when it holds fewer than the quota. Pixels are
    read by position, never by copying the whole image into a
    list, so a 12 megapixel photo costs the quota of reads, not
    12 million tuples in memory.
    """
    width, height = image.size
    total = width * height
    pix = image.load()
    if total <= quota:
        return [pix[x, y] for y in range(height) for x in range(width)]
    step = total / float(quota)
    samples = []
    for i in range(quota):
        index = int(i * step)
        samples.append(pix[index % width, index // width])
    return samples


def load_samples(paths, sample_total):
    """Pooled sampled pixels from all photos.

    The sample budget is split evenly across the photos, so no
    one photo crowds out the rest. Raises PaletteError naming
    the photo when one cannot be found or read.
    """
    if not paths:
        raise PaletteError("give at least one photo to sample from")
    per_photo = max(1, sample_total // len(paths))
    pooled = []
    for path in paths:
        if not os.path.exists(path):
            raise PaletteError("cannot find photo: %s" % path)
        if not os.path.isfile(path):
            raise PaletteError("%s is not a file" % path)
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
        except Exception:
            raise PaletteError(
                "%s is not a photo Pillow can read" % path)
        pooled.extend(sample_pixels(image, per_photo))
    if not pooled:
        raise PaletteError("no pixels sampled from the photos given")
    return pooled


# ---------------------------------------------------------------- palette

def _nearest(color, candidates):
    """The candidate closest to color in RGB space.

    Ties break on the candidate itself, so the answer never
    depends on the order candidates happen to arrive in.
    """
    best = None
    best_dist = None
    for cand in candidates:
        dist = ((color[0] - cand[0]) ** 2
                + (color[1] - cand[1]) ** 2
                + (color[2] - cand[2]) ** 2)
        if best_dist is None or dist < best_dist or (
                dist == best_dist and cand < best):
            best = cand
            best_dist = dist
    return best


def _median_cut_colors(pixels, count):
    """Cluster colors from median-cut (PIL quantize).

    Returns the cluster colors PIL found. These are averages of
    their boxes, so they are NOT yet real sampled colors: the
    caller snaps each one to the nearest sampled pixel.
    """
    width = len(pixels)
    probe = Image.new("RGB", (width, 1))
    probe.putdata(pixels)
    try:
        method = Image.Quantize.MEDIANCUT
    except AttributeError:  # Pillow before the Quantize enum
        method = Image.MEDIANCUT
    try:
        dither = Image.Dither.NONE
    except AttributeError:
        dither = 0
    quantized = probe.quantize(colors=count, method=method,
                               dither=dither)
    palette = quantized.getpalette() or []
    colors = []
    for _n, index in quantized.getcolors(maxcolors=width) or []:
        entry = palette[3 * index:3 * index + 3]
        if len(entry) == 3:
            colors.append(tuple(entry))
    return colors


def extract_palette(pixels, count):
    """The palette: up to count real sampled colors, most common first.

    Median-cut finds the clusters, each cluster color is snapped
    to the nearest color actually sampled (so every hex in the
    output is a real color from the photos), duplicates from the
    snapping are dropped, and any shortfall is filled from the
    most frequent sampled colors not already in the palette.
    The result is ordered by how many sampled pixels fall nearest
    to each color, most common first, ties broken by hex value.
    When the photos hold fewer distinct colors than requested,
    the palette holds what there is: no color is ever invented
    to fill a slot.
    """
    distinct = sorted(set(pixels))
    if len(distinct) <= count:
        # Few distinct colors: no clustering needed, every color
        # present is in the palette, ordered by frequency.
        return _order_by_frequency(distinct, pixels)
    clusters = _median_cut_colors(pixels, count)
    palette = []
    seen = set()
    for cluster in clusters:
        snapped = _nearest(cluster, distinct)
        if snapped not in seen:
            seen.add(snapped)
            palette.append(snapped)
    if len(palette) < count:
        # Fill from the most frequent sampled colors not already
        # in the palette (two clusters can snap to one color).
        freq = Counter(pixels)
        ranked = sorted(freq.items(),
                        key=lambda item: (-item[1], item[0]))
        for color, _n in ranked:
            if len(palette) >= count:
                break
            if color not in seen:
                seen.add(color)
                palette.append(color)
    return _order_by_frequency(palette, pixels)


def _order_by_frequency(palette, pixels):
    """Palette colors ordered most common first, ties by hex."""
    counts = Counter(_nearest(pixel, palette) for pixel in pixels)
    return sorted(palette, key=lambda c: (-counts.get(c, 0), c))


# ---------------------------------------------------------------- output

def rgb_to_hex(color):
    """(255, 0, 0) -> '#ff0000'."""
    return "#%02x%02x%02x" % color


def format_output(palette):
    """The hex list plus the CSS variables block, as one string.

    One hex per line, a blank line, then a :root block with one
    --color-N variable per palette color, in the same order.
    """
    hexes = [rgb_to_hex(color) for color in palette]
    lines = list(hexes)
    lines.append("")
    lines.append(":root {")
    for i, hex_value in enumerate(hexes, start=1):
        lines.append("  --color-%d: %s;" % (i, hex_value))
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- debug log

def make_logger(log_dir_path=None):
    """The T21 debug log layer, wired to this tool."""
    from debug_log import DebugLogger
    logger = DebugLogger(APP_NAME, VERSION,
                         log_dir=log_dir_path or "logs")
    logger.register_dependency("Pillow")
    logger.set_setting("app_version", VERSION)
    logger.register_service(
        "network and services",
        lambda: "none: this tool has no network and no services")
    return logger


def cmd_debug_report():
    """Write a debug report and print where it went."""
    logger = make_logger()
    path = logger.generate_report()
    print("Debug report written to %s" % path)
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(
        prog="photo_palette.py",
        description="Photo Palette (BNB-TOOLS T35): sample pixels "
                    "from photos and pull out a palette of real "
                    "colors, as a hex list plus CSS variables. "
                    "Every hex is a color actually sampled from "
                    "the photos. Sampling is evenly spaced and "
                    "deterministic: the same photos always give "
                    "the same palette.")
    parser.add_argument("photos", nargs="*", metavar="PHOTO",
                        help="photo(s) to sample colors from")
    parser.add_argument("--colors", type=int, default=DEFAULT_COLORS,
                        help="palette size, 1 to 256 "
                             "(default: %d)" % DEFAULT_COLORS)
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help="pixels to sample across all photos "
                             "(default: %d)" % DEFAULT_SAMPLE)
    parser.add_argument("--out", default=None, metavar="FILE",
                        help="write the palette to this file "
                             "instead of stdout")
    parser.add_argument("--debug-report", action="store_true",
                        help="write a debug report and print its "
                             "path, instead of building a palette")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + VERSION)
    return parser


def run(argv=None):
    """Run the tool. Returns an exit code, never raises."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.debug_report:
        try:
            return cmd_debug_report()
        except OSError as exc:
            print("error: cannot write the debug report: %s" % exc,
                  file=sys.stderr)
            return 1
    if Image is None:
        # The T31 missing-dependency guard: plain words, exit 1,
        # never a traceback. Checked here, not at import, so
        # --help, --version, and --debug-report still work
        # without Pillow installed.
        print("error: photo-palette needs PIL (Pillow) to read "
              "photos, and it is not installed for this Python.",
              file=sys.stderr)
        print("Install it with: python3 -m pip install Pillow",
              file=sys.stderr)
        return 1
    if not 1 <= args.colors <= MAX_COLORS:
        print("error: --colors must be between 1 and 256, "
              "got %d" % args.colors, file=sys.stderr)
        return 1
    if args.sample < 1:
        print("error: --sample must be at least 1, got %d"
              % args.sample, file=sys.stderr)
        return 1
    try:
        pixels = load_samples(args.photos, args.sample)
    except PaletteError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    palette = extract_palette(pixels, args.colors)
    text = format_output(palette)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 1
        print("Wrote %s" % args.out)
        return 0
    sys.stdout.write(text)
    return 0


def main(argv=None):
    try:
        return run(argv)
    except Exception as exc:  # last resort: never a traceback
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
