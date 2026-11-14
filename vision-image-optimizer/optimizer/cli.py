"""Command line for Vision Image Optimizer.

    python -m optimizer --help
    python -m optimizer optimize photo.png --width 512
    python -m optimizer describe photo.png
    python -m optimizer cache-clear
    python -m optimizer debug-report

The CLI works while the GUI runs. It needs Pillow only — no Qt.
"""

import argparse
import os
import sys

from . import __version__
from . import core
from .debug_log import DebugLogger, check_ollama
from .ollama import (DEFAULT_FAST_MODEL, DEFAULT_PROMPT,
                     DEFAULT_SMART_MODEL, DEFAULT_URL, OllamaClient,
                     OllamaError)
from .settings import Settings, cache_dir, log_dir


def make_logger(settings=None):
    """The debug log layer, wired to this app's services + settings."""
    logger = DebugLogger("vision-image-optimizer", __version__,
                         log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.register_dependency("Pillow")
    if settings is None:
        settings = Settings()
    for key, value in settings.all_values().items():
        logger.set_setting(key, value)
    url = settings.get("ollama_url")
    logger.register_service("ollama",
                            lambda: check_ollama(url, timeout=2))
    return logger


def _parse_crop(text):
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError("crop needs four numbers: x,y,w,h")
    return tuple(int(p) for p in parts)


def _add_optimize_args(parser):
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


def _optimize_settings(args, settings):
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
    return core.ImageCache(cache_dir(), enabled=enabled)


def cmd_optimize(args):
    settings = Settings()
    opts = _optimize_settings(args, settings)
    cache = _get_cache(settings, args.no_cache)
    if not os.path.isfile(args.file):
        print("No such file: %s" % args.file, file=sys.stderr)
        return 1
    with open(args.file, "rb") as fh:
        image_bytes = fh.read()
    result = cache.get_optimized(image_bytes, opts)
    if result is None:
        result = core.optimize_bytes(image_bytes, opts)
        cache.put_optimized(image_bytes, opts, result)
        cache_note = ""
    else:
        cache_note = " (from cache)"
    out_dir = args.out_dir or settings.get("output_folder") or None
    dest, result = core.write_optimized(args.file, out_dir, opts,
                                        result)
    print("Wrote %s%s" % (dest, cache_note))
    print("Size: %s to %s"
          % (core.human_size(result["bytes_before"]),
             core.human_size(result["bytes_after"])))
    print("Vision tokens: %d to %d"
          % (result["tokens_before"], result["tokens_after"]))
    return 0


def cmd_describe(args):
    settings = Settings()
    opts = _optimize_settings(args, settings)
    cache = _get_cache(settings, args.no_cache)
    if not os.path.isfile(args.file):
        print("No such file: %s" % args.file, file=sys.stderr)
        return 1
    with open(args.file, "rb") as fh:
        image_bytes = fh.read()
    result = cache.get_optimized(image_bytes, opts)
    if result is None:
        result = core.optimize_bytes(image_bytes, opts)
        cache.put_optimized(image_bytes, opts, result)
    prompt = args.prompt or settings.get("prompt")
    fast_model = args.fast_model or settings.get("fast_model")
    smart_model = args.smart_model or settings.get("smart_model")
    url = args.ollama_url or settings.get("ollama_url")
    record = cache.get_description(result["data"], prompt, fast_model,
                                   smart_model)
    if record is not None:
        print(record["text"])
        print()
        print("Model: %s (from cache)" % record["model_used"])
    else:
        client = OllamaClient(url)
        try:
            found = client.describe(result["data"], prompt, fast_model,
                                    smart_model)
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        record = found.to_record()
        cache.put_description(result["data"], prompt, fast_model,
                              smart_model, record)
        print(found.text)
        print()
        print("Model: %s" % found.model_used)
    measure = core.describe_measurements(
        record.get("fast_seconds"), record.get("smart_seconds"),
        result["tokens_before"], result["tokens_after"],
        result["bytes_before"], result["bytes_after"])
    print(core.format_measurements(measure))
    return 0


def cmd_cache_clear(_args):
    cache = core.ImageCache(cache_dir())
    removed, freed = cache.clear()
    print("Cache cleared: %d files removed, %s freed."
          % (removed, core.human_size(freed)))
    return 0


def cmd_debug_report(args):
    logger = make_logger()
    path = logger.generate_report(args.out)
    print("Debug report written to %s" % path)
    print("Send it to broke.n.bored.studio@gmail.com if something "
          "is broken.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="vision-image-optimizer",
        description="Shrink pictures before a local vision model "
                    "looks at them, so each look costs fewer vision "
                    "tokens and less time.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")

    opt = sub.add_parser(
        "optimize",
        help="resize, compress, or crop a picture and save the copy")
    opt.add_argument("file", help="the picture to optimize")
    opt.add_argument("--out-dir", default=None,
                     help="folder for the optimized copy "
                          "(default: an 'optimized' folder next to "
                          "the picture)")
    _add_optimize_args(opt)
    opt.set_defaults(func=cmd_optimize)

    desc = sub.add_parser(
        "describe",
        help="describe a picture with the local vision model "
             "(after shrinking it)")
    desc.add_argument("file", help="the picture to describe")
    desc.add_argument("--prompt", default=None,
                      help="what to ask the model "
                           "(default: the saved prompt)")
    desc.add_argument("--fast-model", default=None,
                      help="the small model that looks first "
                           "(default: %s)" % DEFAULT_FAST_MODEL)
    desc.add_argument("--smart-model", default=None,
                      help="the careful model that looks second "
                           "(default: %s)" % DEFAULT_SMART_MODEL)
    desc.add_argument("--ollama-url", default=None,
                      help="Ollama address "
                           "(default: %s)" % DEFAULT_URL)
    _add_optimize_args(desc)
    desc.set_defaults(func=cmd_describe)

    clear = sub.add_parser("cache-clear",
                           help="empty the optimized-picture and "
                                "description cache")
    clear.set_defaults(func=cmd_cache_clear)

    report = sub.add_parser(
        "debug-report",
        help="write a debug report file (safe to email)")
    report.add_argument("--out", default=None,
                        help="report path (default: the log folder)")
    report.set_defaults(func=cmd_debug_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("Could not read or write a file: %s" % exc,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
