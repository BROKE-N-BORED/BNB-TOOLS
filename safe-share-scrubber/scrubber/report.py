"""Report builder for Safe Share Scrubber. No Qt import here.

A report names the file, the safe copy, the secrets found by kind
with line numbers, and a plain verdict line. It never echoes a
secret value: findings carry kind and line only, and file names
shown in the report pass through the scrubber first.
"""

from pathlib import Path

from . import core

# The honest caveat, in plain words. It also appears as a label in
# the window and in the How to Use window (gui.py imports it).
CAVEAT_TEXT = (
    "This scrubber works from patterns. It can only catch secrets "
    "it has a pattern for, so it cannot prove a file holds no "
    "secret it does not know about. Read the safe copy before you "
    "share it."
)


def _display_name(text):
    """A file name for display, scrubbed in case it carries a
    secret-shaped string itself."""
    return core.scrub_text(str(text))[0]


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


def build_file_report(result):
    """The per-file report text for one scrub_file result dict."""
    out = []
    out.append("Safe Share Scrubber report")
    out.append("File: %s" % _display_name(result["path"]))
    if result.get("error"):
        out.append("Could not read or write this file: %s"
                   % result["error"])
        out.append("No safe copy was written.")
    elif result.get("skipped"):
        out.append("Skipped: %s." % result["skipped_reason"])
        out.append("No safe copy was written.")
    else:
        out.append("Safe copy: %s"
                   % _display_name(result["safe_path"]))
        findings = result.get("findings") or []
        out.append("Secrets found: %d" % len(findings))
        for kind, lines in sorted(_group_findings(findings).items()):
            out.append("  %s: %s" % (kind, _lines_text(lines)))
        if not findings:
            out.append("  None. The safe copy matches the original.")
    out.append("Verdict: %s" % result["verdict"])
    out.append("")
    out.append(CAVEAT_TEXT)
    return "\n".join(out) + "\n"


def build_report(results):
    """The combined report for a list of scrub_file results."""
    return "\n".join(build_file_report(result)
                     for result in results)


def report_file_path(path):
    """debug.log -> debug.safe-report.txt, next to the file."""
    path = Path(path)
    return path.with_name(path.stem + ".safe-report.txt")


def write_report_file(result):
    """Write the per-file report next to the input file.

    Returns the report path as a string.
    """
    dest = report_file_path(result["path"])
    dest.write_text(build_file_report(result), encoding="utf-8")
    return str(dest)
