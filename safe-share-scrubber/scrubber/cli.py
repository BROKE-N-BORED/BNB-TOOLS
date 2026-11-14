"""Command line for Safe Share Scrubber.

    python -m scrubber --help
    python -m scrubber scrub debug.log notes.txt
    python -m scrubber debug-report

The CLI works while the GUI runs: it takes no single-instance lock.
It needs no Qt. It never logs file contents, only file names,
counts, kinds, and line numbers.
"""

import argparse
import os
import sys

from . import __version__
from . import core
from . import report as report_mod
from .debug_log import DebugLogger
from .settings import log_dir


def make_logger():
    """The debug log layer, wired to this app.

    Settings: the app version only, no secrets ever. Services: none
    to check, this app has no network and no services, and the
    context snapshot says so plainly.
    """
    logger = DebugLogger("safe-share-scrubber", __version__,
                         log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.set_setting("app_version", __version__)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger


def safe_log_text(text):
    """User text before it goes near the log: scrubbed, so even a
    file name carrying a secret-shaped string cannot leak."""
    return core.scrub_text(str(text))[0]


def cmd_scrub(args):
    logger = make_logger()
    logger.install_crash_handler()
    failures = 0
    for path in args.files:
        if not os.path.isfile(path):
            print("No such file: %s" % path, file=sys.stderr)
            logger.warning("scrub asked for a missing file: %s",
                           safe_log_text(path))
            failures += 1
            continue
        result = core.scrub_file(path)
        if result.get("error"):
            print("Could not scrub %s: %s" % (path, result["error"]),
                  file=sys.stderr)
            logger.warning("scrub failed for %s: %s",
                           safe_log_text(path), result["error"])
            failures += 1
            continue
        try:
            report_path = report_mod.write_report_file(result)
        except OSError as exc:
            print("Could not write the report for %s: %s"
                  % (path, exc), file=sys.stderr)
            logger.warning("report write failed for %s: %s",
                           safe_log_text(path), exc)
            failures += 1
            continue
        print(report_mod.build_file_report(result))
        print("Report written to %s" % report_path)
        print()
        kinds = sorted({f["kind"] for f in result["findings"]})
        logger.action(
            "scrubbed %s: %d finding(s)%s"
            % (safe_log_text(os.path.basename(path)),
               len(result["findings"]),
               (" (%s)" % ", ".join(kinds)) if kinds else ""))
    return 1 if failures else 0


def cmd_debug_report(args):
    logger = make_logger()
    logger.install_crash_handler()
    path = logger.generate_report(args.out)
    print("Debug report written to %s" % path)
    print("Send it to broke.n.bored.studio@gmail.com if something "
          "is broken.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="safe-share-scrubber",
        description="Find secrets in a text file, redact them, and "
                    "hand back a safe copy plus a short report. "
                    "The original file is never changed.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")

    scrub = sub.add_parser(
        "scrub",
        help="scrub one or more files: write a safe copy and a "
             "report for each")
    scrub.add_argument("files", nargs="+",
                       help="the files to scrub")
    scrub.set_defaults(func=cmd_scrub)

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
    except OSError as exc:
        print("Could not read or write a file: %s" % exc,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
