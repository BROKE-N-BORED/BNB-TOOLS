"""Command line for Safe Share Scrubber.

    python -m scrubber --help
    python -m scrubber scrub debug.log notes.txt
    python -m scrubber scrub --json debug.log
    python -m scrubber verify debug.log notes.txt
    python -m scrubber verify --json debug.log
    python -m scrubber debug-report

scrub writes a safe copy and a report next to each file. verify
only scans: it writes nothing, and exits 0 when every file is
clean, 1 when any secret is found, 2 when a file could not be
read or scanned.

The CLI works while the GUI runs: it takes no single-instance lock.
It needs no Qt. It never logs file contents, only file names,
counts, kinds, and line numbers.
"""

import argparse
import json
import os
import sys

from . import __version__
from . import core
from . import report as report_mod
from .logsetup import make_logger  # noqa: F401  (re-exported: gui.py
# and tests import make_logger from this module)


def safe_log_text(text):
    """User text before it goes near the log: scrubbed, so even a
    file name carrying a secret-shaped string cannot leak."""
    return core.scrub_text(str(text))[0]


# The honest caveat for verify, in plain words: the same warning
# as report.CAVEAT_TEXT, minus the safe-copy sentence, because
# verify writes no safe copy.
VERIFY_CAVEAT = (
    "This scanner works from patterns. It can only catch secrets "
    "it has a pattern for, so it cannot prove a file holds no "
    "secret it does not know about."
)


def _group_findings(findings):
    """Findings grouped by kind, each with its sorted line list."""
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding["kind"], []).append(
            finding["line"])
    return {kind: sorted(lines) for kind, lines in grouped.items()}


def _lines_text(lines):
    if len(lines) == 1:
        return "line %d" % lines[0]
    return "lines %s" % ", ".join(str(n) for n in lines)


def _kinds_text(findings):
    kinds = sorted({f["kind"] for f in findings})
    return (" (%s)" % ", ".join(kinds)) if kinds else ""


def cmd_scrub(args):
    logger = make_logger()
    logger.install_crash_handler()
    as_json = getattr(args, "json", False)
    failures = 0
    results = [] if as_json else None
    for path in args.files:
        if not os.path.isfile(path):
            print("No such file: %s" % path, file=sys.stderr)
            logger.warning("scrub asked for a missing file: %s",
                           safe_log_text(path))
            failures += 1
            if as_json:
                results.append({
                    "path": path,
                    "safe_path": None,
                    "findings": [],
                    "secrets_found": 0,
                    "verdict": core.VERDICT_UNREADABLE,
                    "skipped": False,
                    "skipped_reason": None,
                    "error": "No such file",
                    "report_path": None,
                })
            continue
        result = core.scrub_file(path)
        if result.get("error"):
            print("Could not scrub %s: %s" % (path, result["error"]),
                  file=sys.stderr)
            logger.warning("scrub failed for %s: %s",
                           safe_log_text(path), result["error"])
            failures += 1
            if as_json:
                result["report_path"] = None
                results.append(result)
            continue
        try:
            report_path = report_mod.write_report_file(result)
        except OSError as exc:
            print("Could not write the report for %s: %s"
                  % (path, exc), file=sys.stderr)
            logger.warning("report write failed for %s: %s",
                           safe_log_text(path), exc)
            failures += 1
            if as_json:
                result["report_path"] = None
                results.append(result)
            continue
        if as_json:
            result["report_path"] = report_path
            results.append(result)
        else:
            print(report_mod.build_file_report(result))
            print("Report written to %s" % report_path)
            print()
        logger.action(
            "scrubbed %s: %d finding(s)%s"
            % (safe_log_text(os.path.basename(path)),
               len(result["findings"]),
               _kinds_text(result["findings"])))
    if as_json:
        print(json.dumps(results, indent=2))
    return 1 if failures else 0


def scan_file_for_verify(path):
    """Read-only scan of one file for the verify command.

    Uses the engine's scrub_text on the file's content; nothing is
    written anywhere. Returns a dict: path, findings [{kind,
    line}], secrets_found, verdict ("safe", "unsafe", or
    "skipped"), skipped_reason, error. A file that cannot be read
    or scanned comes back with verdict "skipped" and the reason in
    error (missing, not a file, unreadable) or skipped_reason
    (binary). The binary test mirrors core: NUL bytes or not
    UTF-8 text, so verify and scrub agree on what is binary.
    """
    result = {
        "path": path,
        "findings": [],
        "secrets_found": 0,
        "verdict": "skipped",
        "skipped_reason": None,
        "error": None,
    }
    if not os.path.exists(path):
        result["error"] = "No such file"
        return result
    if not os.path.isfile(path):
        result["error"] = "Not a file"
        return result
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        result["error"] = str(exc)
        return result
    if b"\x00" in data:
        result["skipped_reason"] = "binary file (contains NUL bytes)"
        return result
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        result["skipped_reason"] = "binary file (not UTF-8 text)"
        return result
    _scrubbed, findings = core.scrub_text(text)
    result["findings"] = [{"kind": f["kind"], "line": f["line"]}
                          for f in findings]
    result["secrets_found"] = len(findings)
    result["verdict"] = "unsafe" if findings else "safe"
    return result


def build_verify_text(result):
    """The per-file human report for one verify scan result.

    Mirrors the scrub report style: file, secrets by kind with
    line numbers, and a plain verdict line. No safe copy is ever
    mentioned: verify writes none.
    """
    out = []
    out.append("File: %s" % safe_log_text(result["path"]))
    if result.get("error"):
        out.append("Could not scan this file: %s" % result["error"])
        out.append("Verdict: Not scanned")
    elif result.get("skipped_reason"):
        out.append("Skipped: %s." % result["skipped_reason"])
        out.append("Verdict: Not scanned")
    else:
        findings = result["findings"]
        out.append("Secrets found: %d" % len(findings))
        for kind, lines in sorted(
                _group_findings(findings).items()):
            out.append("  %s: %s" % (kind, _lines_text(lines)))
        if not findings:
            out.append("  None.")
        if findings:
            out.append("Verdict: Not safe to share: secrets found")
        else:
            out.append("Verdict: Safe to share")
    return "\n".join(out) + "\n"


def cmd_verify(args):
    """verify: read-only scan. Exit 0 when every file is clean,
    1 when any secret is found, 2 when any file could not be read
    or scanned. An unscanned file outranks a found secret: exit 2
    wins over exit 1, because the verdict is incomplete."""
    logger = make_logger()
    logger.install_crash_handler()
    as_json = getattr(args, "json", False)
    results = [scan_file_for_verify(path) for path in args.files]
    for result in results:
        name = safe_log_text(os.path.basename(result["path"]))
        if result.get("error"):
            logger.warning("verify could not scan %s: %s",
                           name, result["error"])
        elif result.get("skipped_reason"):
            logger.warning("verify skipped %s: %s",
                           name, result["skipped_reason"])
        else:
            logger.action(
                "verified %s: %d finding(s)%s"
                % (name, len(result["findings"]),
                   _kinds_text(result["findings"])))
    if as_json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(build_verify_text(result))
        print(VERIFY_CAVEAT)
    if any(r.get("error") or r.get("skipped_reason")
           for r in results):
        return 2
    if any(r["secrets_found"] for r in results):
        return 1
    return 0


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
        description="Find secrets in text files. scrub redacts "
                    "them into a safe copy plus a report; verify "
                    "only scans and reports, writing nothing. "
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
    scrub.add_argument("--json", action="store_true",
                       help="print the results as JSON instead of "
                            "the human report")
    scrub.set_defaults(func=cmd_scrub)

    verify = sub.add_parser(
        "verify",
        help="scan one or more files without writing anything: "
             "exit 0 when clean, 1 when a secret is found, "
             "2 when a file could not be read or scanned")
    verify.add_argument("files", nargs="+",
                        help="the files to scan")
    verify.add_argument("--json", action="store_true",
                        help="print the results as JSON instead of "
                             "the human report")
    verify.set_defaults(func=cmd_verify)

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
