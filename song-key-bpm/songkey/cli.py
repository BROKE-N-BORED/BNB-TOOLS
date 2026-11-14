"""Command line for Song Key BPM.

    songkey-cli --help
    songkey-cli analyze FILE [FILE ...] [--json] [--out FILE]
    songkey-cli export RESULTS.json [--format csv|json|both]
        [--out FILE]
    songkey-cli debug-report

The wrappers song-key-analyze and song-key-export call the
analyze and export commands directly. The CLI works with no Qt
installed and no display.

Analyze takes files and/or folders; a folder contributes every
audio file under it (WAV, MP3, FLAC, OGG). Files that cannot be
read are skipped with a plain warning and the rest still run.
Exit codes: 0 when at least one file was analyzed, 1 when none
was, 2 on a usage error.
"""

import argparse
import json
import os
import sys

from . import APP_NAME, __version__
from .analyze import analyze_file
from .decode import SUPPORTED_EXTENSIONS
from .export import to_csv, to_json, write_csv, write_json
from .logsetup import make_logger

REPORT_EMAIL = "broke.n.bored.studio@gmail.com"


def collect_files(paths):
    """Expand files and folders into a sorted list of audio paths.

    Folders are walked recursively; only supported audio files
    are picked up. A path that is neither a file nor a folder is
    reported on stderr and skipped. Returns (files, skipped):
    skipped counts the paths that were not usable.
    """
    files = []
    skipped = 0
    for path in paths:
        if os.path.isfile(path):
            files.append(path)
        elif os.path.isdir(path):
            found = []
            for root, dirs, names in os.walk(path):
                dirs.sort()
                for name in sorted(names):
                    if name.lower().endswith(SUPPORTED_EXTENSIONS):
                        found.append(os.path.join(root, name))
            if not found:
                print("Warning: %s has no audio files in it, "
                      "skipped" % path, file=sys.stderr)
                skipped += 1
            files.extend(found)
        else:
            print("Warning: %s is not a file or folder, skipped"
                  % path, file=sys.stderr)
            skipped += 1
    return files, skipped


def _describe(result):
    """One result as a plain one-line summary."""
    if result["error"]:
        return "%s: %s" % (result["file"], result["error"])
    bpm = result["bpm"]
    if bpm is None:
        bpm_text = "BPM unknown"
    else:
        bpm_text = "%.1f BPM (%s)" % (bpm, result["bpm_confidence"])
    key = result["key"]
    if key is None:
        key_text = "key unknown"
    else:
        key_text = "key %s (%s)" % (key, result["key_confidence"])
        if result["key_confidence"] == "low" and result[
                "key_runner_up"]:
            key_text += ", close call with %s" % result[
                "key_runner_up"]
    return "%s: %s, %s, %.1fs" % (result["file"], bpm_text,
                                  key_text, result["duration"])


def cmd_analyze(args):
    logger = make_logger()
    logger.install_crash_handler()
    logger.action("analyze started (%d path(s))" % len(args.paths))
    files, _skipped = collect_files(args.paths)
    results = []
    succeeded = 0
    for path in files:
        result = analyze_file(path)
        results.append(result)
        if result["error"]:
            print("Warning: %s" % result["error"], file=sys.stderr)
            logger.warning("analyze failed for %s: %s"
                           % (path, result["error"]))
        else:
            succeeded += 1
            logger.info("analyzed %s: %s BPM, key %s"
                        % (result["file"], result["bpm"],
                           result["key"]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
        note = "Wrote %d result(s) to %s" % (len(results), args.out)
        if args.json:
            print(note, file=sys.stderr)
        else:
            print(note)
    if args.json:
        print(json.dumps(results, indent=2))
    elif not args.out:
        for result in results:
            print(_describe(result))
    logger.action("analyze finished (%d of %d analyzed)"
                  % (succeeded, len(results)))
    if succeeded == 0:
        if not files:
            print("No audio files to analyze.", file=sys.stderr)
        return 1
    return 0


def _load_results(path):
    """Read an analyze JSON file; return the results list.

    Raises ValueError with a plain message when the file cannot
    be read or does not hold results.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise ValueError("Could not read %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise ValueError("%s is not valid JSON: %s" % (path, exc))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data):
        raise ValueError("%s does not hold analysis results"
                         % path)
    return data


def cmd_export(args):
    logger = make_logger()
    logger.install_crash_handler()
    try:
        results = _load_results(args.input)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    logger.action("export started (%d result(s), format %s)"
                  % (len(results), args.format))
    if args.format == "both":
        base, _ext = os.path.splitext(args.out)
        csv_path = base + ".csv"
        json_path = base + ".json"
        write_csv(results, csv_path)
        write_json(results, json_path)
        print("Wrote %s" % csv_path)
        print("Wrote %s" % json_path)
        return 0
    if args.format == "csv":
        text = to_csv(results)
    else:
        text = to_json(results)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("Wrote %s" % args.out)
    else:
        print(text, end="")
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
        prog="songkey-cli",
        description="Song Key BPM: find the key and BPM of audio "
                    "files, on this machine, with no network.")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser(
        "analyze",
        description="Song Key BPM: analyze audio files and/or "
                    "folders and report each file's BPM and key.",
        help="analyze audio files and/or folders")
    analyze.add_argument("paths", nargs="+", metavar="PATH",
                         help="audio file(s) and/or folder(s) to "
                              "analyze")
    analyze.add_argument("--json", action="store_true",
                         help="print the results as JSON")
    analyze.add_argument("--out", default=None,
                         help="write the results JSON to this file")
    analyze.add_argument("--version", action="version",
                         version="%s %s" % (APP_NAME, __version__))

    export = sub.add_parser(
        "export",
        description="Song Key BPM: convert an analyze JSON file "
                    "to a CSV and/or JSON table.",
        help="convert an analyze JSON file to a CSV and/or JSON "
             "table")
    export.add_argument("input", metavar="RESULTS.json",
                        help="the analyze JSON file to convert")
    export.add_argument("--format", default="csv",
                        choices=("csv", "json", "both"),
                        help="table format (default: csv)")
    export.add_argument("--out", default=None,
                         help="file to write (default: print to "
                              "stdout; required with --format both)")
    export.add_argument("--version", action="version",
                        version="%s %s" % (APP_NAME, __version__))

    sub.add_parser("debug-report",
                   help="write a debug report and print its path")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return cmd_analyze(args)
    if args.command == "export":
        if args.format == "both" and not args.out:
            parser.error("--format both needs --out (two files "
                         "are written)")
        return cmd_export(args)
    if args.command == "debug-report":
        return cmd_debug_report(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
