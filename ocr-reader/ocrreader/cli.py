"""Command line for OCR Reader.

    ocrreader-cli --help
    ocrreader-cli read IMAGE [IMAGE ...] [--lang eng]
        [--out FILE] [--json]
    ocrreader-cli clean [FILE] [--out FILE] [--json]
    ocrreader-cli debug-report

The wrappers ocr-read and ocr-clean call the read and clean
commands directly. The CLI works with no Qt installed and no
display. Exit codes: 0 ok, 1 nothing read / binary missing /
unreadable file, 2 on a usage error.

read --json prints a JSON list, one object per input file:
{"path", "file", "text", "pages", "language", "error"}.
error is null on success, else a plain string. Without --json
the text prints to stdout, multiple files joined with a
"\n--- <file> ---\n" marker between them; --out writes that
same output to a file instead.
"""

import argparse
import json
import os
import sys

from . import APP_NAME, __version__
from .clean import clean_text
from .engine import read_files
from .logsetup import make_logger

REPORT_EMAIL = "broke.n.bored.studio@gmail.com"


def _write_out(path, content):
    """Write content to path; return an error string or None."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        return "Could not write %s: %s" % (path, exc)
    return None


def cmd_read(args):
    logger = make_logger()
    logger.install_crash_handler()
    logger.action("read started (%d file(s))" % len(args.paths))
    results = read_files(args.paths, lang=args.lang)
    succeeded = 0
    for result in results:
        if result["error"]:
            print("Warning: %s" % result["error"], file=sys.stderr)
            logger.warning("read failed for %s: %s"
                           % (result["path"], result["error"]))
        else:
            succeeded += 1
            logger.info("read %s (%d page(s))"
                        % (result["file"], result["pages"]))
    if args.json:
        content = json.dumps(results, indent=2) + "\n"
    else:
        content = ""
        for index, result in enumerate(
                item for item in results if not item["error"]):
            if index:
                content += "\n--- %s ---\n" % result["file"]
            content += result["text"]
    if args.out:
        error = _write_out(args.out, content)
        if error:
            print(error, file=sys.stderr)
            return 1
        note = "Wrote %s" % args.out
        if args.json:
            print(note, file=sys.stderr)
        else:
            print(note)
    else:
        print(content, end="")
    logger.action("read finished (%d of %d read)"
                  % (succeeded, len(results)))
    if succeeded == 0:
        print("Nothing was read.", file=sys.stderr)
        return 1
    return 0


def cmd_clean(args):
    logger = make_logger()
    logger.install_crash_handler()
    if args.input:
        try:
            with open(args.input, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print("Could not read %s: %s" % (args.input, exc),
                  file=sys.stderr)
            return 1
    else:
        text = sys.stdin.read()
    logger.action("clean started (%s)"
                  % (args.input or "stdin"))
    cleaned, changes = clean_text(text)
    logger.info("clean finished (%d change(s))"
                % len(changes))
    if args.json:
        content = json.dumps({"text": cleaned, "changes": changes},
                             indent=2) + "\n"
    else:
        content = cleaned
        if content and not content.endswith("\n"):
            content += "\n"
    if args.out:
        error = _write_out(args.out, content)
        if error:
            print(error, file=sys.stderr)
            return 1
        note = "Wrote %s" % args.out
        if args.json:
            print(note, file=sys.stderr)
        else:
            print(note)
    else:
        print(content, end="")
    return 0


def cmd_debug_report(args):
    logger = make_logger()
    logger.install_crash_handler()
    path = logger.generate_report()
    print("Debug report written to %s" % path)
    print("Send it to %s if something is broken." % REPORT_EMAIL)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ocrreader-cli",
        description="OCR Reader: read the text out of pictures "
                    "and scanned pages, on this machine, with no "
                    "network.")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="command")

    read = sub.add_parser(
        "read",
        description="OCR Reader: read the text out of image "
                    "files (and PDFs) with Tesseract.",
        help="read the text out of image files (and PDFs)")
    read.add_argument("paths", nargs="+", metavar="PATH",
                      help="image file(s) to read")
    read.add_argument("--lang", default="eng",
                      help="tesseract language (default: eng)")
    read.add_argument("--json", action="store_true",
                      help="print the results as JSON")
    read.add_argument("--out", default=None,
                      help="write the output to this file instead "
                           "of stdout")
    read.add_argument("--version", action="version",
                      version="%s %s" % (APP_NAME, __version__))

    clean = sub.add_parser(
        "clean",
        description="OCR Reader: tidy OCR text (whitespace and "
                    "layout only, words are never changed). Reads "
                    "a file, or stdin when no file is given.",
        help="tidy OCR text (whitespace and layout only)")
    clean.add_argument("input", nargs="?", default=None,
                       metavar="FILE",
                       help="text file to clean (default: stdin)")
    clean.add_argument("--json", action="store_true",
                      help="print the result as JSON")
    clean.add_argument("--out", default=None,
                       help="write the output to this file instead "
                            "of stdout")
    clean.add_argument("--version", action="version",
                       version="%s %s" % (APP_NAME, __version__))

    sub.add_parser("debug-report",
                   help="write a debug report and print its path")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "read":
        return cmd_read(args)
    if args.command == "clean":
        return cmd_clean(args)
    if args.command == "debug-report":
        return cmd_debug_report(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
