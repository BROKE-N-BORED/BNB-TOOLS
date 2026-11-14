"""Combined command line for Vision Image Optimizer.

    python -m optimizer --help
    python -m optimizer optimize photo.png --width 512
    python -m optimizer describe photo-512w.jpg
    python -m optimizer cache-clear
    python -m optimizer cache-stats
    python -m optimizer debug-report

A thin shell over the small chainable pieces: optimize delegates
to the shrink module, describe delegates to the describe module.
Each piece also runs on its own (python -m optimizer.shrink,
python -m optimizer.describe). Describe works on the file exactly
as given, so shrink first when the picture is large.

The CLI works while the GUI runs. It needs Pillow only, no Qt.
"""

import argparse
import json
import sys

from . import __version__
from . import describe, shrink, tokens
from .cache import ImageCache
from .logsetup import make_logger
from .settings import cache_dir


def cmd_cache_clear(_args):
    cache = ImageCache(cache_dir())
    removed, freed = cache.clear()
    print("Cache cleared: %d files removed, %s freed."
          % (removed, tokens.human_size(freed)))
    return 0


def cmd_cache_stats(args):
    cache = ImageCache(cache_dir())
    optimized, descriptions, total = cache.stats()
    if args.json:
        print(json.dumps({"optimized": optimized,
                          "descriptions": descriptions,
                          "bytes": total}))
    else:
        print("Cache: %d optimized picture(s), %d description(s), %s"
              % (optimized, descriptions, tokens.human_size(total)))
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
    shrink.add_arguments(opt)
    opt.set_defaults(func=shrink.run)

    desc = sub.add_parser(
        "describe",
        help="describe a picture with the local vision model, "
             "exactly as given")
    describe.add_arguments(desc)
    desc.set_defaults(func=describe.run)

    clear = sub.add_parser("cache-clear",
                           help="empty the optimized-picture and "
                                "description cache")
    clear.set_defaults(func=cmd_cache_clear)

    stats = sub.add_parser("cache-stats",
                           help="show how much the cache holds")
    stats.add_argument("--json", action="store_true",
                       help="print one JSON object instead of "
                            "a human-readable line")
    stats.set_defaults(func=cmd_cache_stats)

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
