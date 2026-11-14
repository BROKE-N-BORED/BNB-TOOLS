"""Shrink step for Vision Image Optimizer: resize, compress, crop.

One small piece of the chain: it takes a picture and writes a
smaller copy, nothing else. Describing is the describe module's
job; chain them to shrink a picture and then describe the copy.

    python -m optimizer.shrink photo.png --width 512
    python -m optimizer.shrink photo.png --width 512 --json
"""

import argparse
import io
import json
import os
import sys

from PIL import Image

from .cache import ImageCache
from .settings import Settings, cache_dir
from .tokens import (clamp_crop, human_size, target_size,
                     vision_tokens)


def default_settings():
    """The optimize settings a fresh install starts with."""
    return {
        "width": 512,
        "quality": 85,
        "format": "JPEG",
        "crop": None,
    }


def optimize_bytes(image_bytes, settings):
    """Resize/compress/crop picture bytes. Returns a result dict.

    settings: {"width": int or None, "quality": int 1-100,
    "format": "JPEG" or "PNG", "crop": (x, y, w, h) or None}.

    The result carries the new bytes plus before/after measurements:
    width, height, tokens, file size.
    """
    fmt = str(settings.get("format", "JPEG")).upper()
    if fmt not in ("JPEG", "PNG"):
        raise ValueError("format must be JPEG or PNG")
    quality = int(settings.get("quality", 85))
    quality = max(1, min(100, quality))
    target_width = settings.get("width")

    with Image.open(io.BytesIO(image_bytes)) as img:
        orig_width, orig_height = img.width, img.height
        work = img
        crop = clamp_crop(settings.get("crop"), orig_width, orig_height)
        if crop is not None:
            x, y, w, h = crop
            work = work.crop((x, y, x + w, y + h))
        new_width, new_height = target_size(
            work.width, work.height, target_width)
        if (new_width, new_height) != (work.width, work.height):
            work = work.resize((new_width, new_height), Image.LANCZOS)
        if fmt == "JPEG" and work.mode in ("RGBA", "LA", "P"):
            work = work.convert("RGB")
        buf = io.BytesIO()
        if fmt == "JPEG":
            work.save(buf, "JPEG", quality=quality, optimize=True)
        else:
            work.save(buf, "PNG", optimize=True)
        out_bytes = buf.getvalue()

    return {
        "data": out_bytes,
        "width": new_width,
        "height": new_height,
        "tokens_before": vision_tokens(orig_width, orig_height),
        "tokens_after": vision_tokens(new_width, new_height),
        "bytes_before": len(image_bytes),
        "bytes_after": len(out_bytes),
        "format": fmt,
    }


def optimize_file(src_path, settings):
    """Optimize one file on disk. Returns the optimize_bytes result."""
    with open(src_path, "rb") as fh:
        return optimize_bytes(fh.read(), settings)


def output_path(src_path, out_dir, width, fmt):
    """Where the optimized copy goes. Never the source path itself.

    Default is a subfolder named "optimized" next to the source.
    The name carries the width so different sizes never collide.
    """
    if out_dir:
        folder = out_dir
    else:
        folder = os.path.join(os.path.dirname(os.path.abspath(src_path)),
                              "optimized")
    stem = os.path.splitext(os.path.basename(src_path))[0]
    ext = ".jpg" if fmt.upper() == "JPEG" else ".png"
    if width is None:
        name = "%s-optimized%s" % (stem, ext)
    else:
        name = "%s-%dw%s" % (stem, width, ext)
    candidate = os.path.join(folder, name)
    if os.path.abspath(candidate) == os.path.abspath(src_path):
        # Same folder and same name would overwrite the original.
        name = "%s-optimized-copy%s" % (stem, ext)
        candidate = os.path.join(folder, name)
    return candidate


def write_optimized(src_path, out_dir, settings, result=None):
    """Optimize a file and write the copy. Returns (path, result).

    Refuses to overwrite the source: if the computed output path is
    the source path, the name gains "-optimized-copy" (see
    output_path). The source file is never touched.
    """
    if result is None:
        result = optimize_file(src_path, settings)
    fmt = str(settings.get("format", "JPEG")).upper()
    dest = output_path(src_path, out_dir, settings.get("width"), fmt)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(result["data"])
    return dest, result


# ------------------------------------------------------------------ CLI


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit 1 with a plain message, not 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, "%s: error: %s\n" % (self.prog, message))


def _parse_crop(text):
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError("crop needs four numbers: x,y,w,h")
    return tuple(int(p) for p in parts)


def add_arguments(parser):
    """The shrink flags, shared by this module and the combined CLI."""
    parser.add_argument("file", help="the picture to shrink")
    parser.add_argument("--out-dir", default=None,
                        help="folder for the shrunk copy "
                             "(default: an 'optimized' folder next to "
                             "the picture)")
    parser.add_argument("--width", type=int, default=None,
                        help="resize to this width in pixels "
                             "(default: the saved size setting)")
    parser.add_argument("--original-width", action="store_true",
                        help="keep the original width (no resize)")
    parser.add_argument("--quality", type=int, default=None,
                        help="JPEG quality 1-100 "
                             "(default: the saved quality setting)")
    parser.add_argument("--format", choices=("JPEG", "PNG"),
                        default=None,
                        help="output format "
                             "(default: the saved format setting)")
    parser.add_argument("--crop", default=None,
                        help="crop box as x,y,w,h in pixels")
    parser.add_argument("--no-cache", action="store_true",
                        help="skip the cache for this run")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object instead of "
                             "human-readable lines")


def build_parser():
    parser = _Parser(
        prog="vision-shrink",
        description="Shrink a picture and save the copy, so a local "
                    "vision model can look at it for fewer tokens.")
    add_arguments(parser)
    return parser


def settings_from_args(args, settings):
    """The optimize settings dict: saved settings, flags on top."""
    opts = settings.optimize_settings()
    if args.original_width:
        opts["width"] = None
    elif args.width is not None:
        opts["width"] = args.width
    if args.quality is not None:
        opts["quality"] = args.quality
    if args.format is not None:
        opts["format"] = args.format
    if args.crop:
        opts["crop"] = _parse_crop(args.crop)
    return opts


def _get_cache(settings, no_cache=False):
    enabled = bool(settings.get("cache_enabled")) and not no_cache
    return ImageCache(cache_dir(), enabled=enabled)


def run(args):
    """Shrink one picture. Returns an exit code (0 ok, 1 failed)."""
    settings = Settings()
    opts = settings_from_args(args, settings)
    cache = _get_cache(settings, args.no_cache)
    if not os.path.isfile(args.file):
        print("No such file: %s" % args.file, file=sys.stderr)
        return 1
    with open(args.file, "rb") as fh:
        image_bytes = fh.read()
    result = cache.get_optimized(image_bytes, opts)
    from_cache = result is not None
    if result is None:
        result = optimize_bytes(image_bytes, opts)
        cache.put_optimized(image_bytes, opts, result)
    out_dir = args.out_dir or settings.get("output_folder") or None
    dest, result = write_optimized(args.file, out_dir, opts, result)
    if args.json:
        print(json.dumps({
            "path": dest,
            "width": result["width"],
            "height": result["height"],
            "tokens_before": result["tokens_before"],
            "tokens_after": result["tokens_after"],
            "bytes_before": result["bytes_before"],
            "bytes_after": result["bytes_after"],
            "format": result["format"],
            "from_cache": from_cache,
        }))
        return 0
    cache_note = " (from cache)" if from_cache else ""
    print("Wrote %s%s" % (dest, cache_note))
    print("Size: %s to %s"
          % (human_size(result["bytes_before"]),
             human_size(result["bytes_after"])))
    print("Vision tokens: %d to %d"
          % (result["tokens_before"], result["tokens_after"]))
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("Could not read or write a file: %s" % exc,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
