#!/usr/bin/env python3
"""Check a task list covers every audit finding.

Pairs with BNB SKILLS audit-findings-task-list-merge: after folding a new
audit's findings into an existing task list, this tool verifies the merge
mechanically instead of by eye.

Inputs (plain text, stdlib only):
- Findings file: one finding per line, `ID: description`
  (e.g. `V-01: probe loads the base model twice`). Blank lines and lines
  starting with `#` are ignored. A line with no `ID:` shape is skipped
  with a warning.
- Task-list file: Markdown. A task starts at a heading or list item whose
  text begins with a task ID (`T1`, `T11`, `C117`, `T2-4`), and covers
  findings listed on a `Covers: ID1, ID2` line under it. `Covers:` lines
  before the first task are ignored with a warning.

Checks:
1. Every finding is covered by at least one task.
2. Every finding ID a task references exists in the findings file.
3. Task IDs are unique; finding IDs are unique.
4. Counts reconcile (reported in the output).

Exit code 0 = pass (every finding covered, no unknown references, no
duplicate IDs). Exit code 1 = fail. Exit code 2 = usage error (missing
file, no findings parsed).

Usage:
    python3 coverage_check.py findings.txt tasks.md
    python3 coverage_check.py findings.txt tasks.md --json
"""

import argparse
import json
import re
import sys

FINDING_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.-]*)\s*:\s*\S")
TASK_RE = re.compile(r"^\s*(?:#{1,4}\s+|[-*]\s+(?:\*\*)?)([TC]\d+(?:-\d+)?)\b")
COVERS_RE = re.compile(r"\bcovers\s*:\s*(.+)$", re.IGNORECASE)
ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")


def parse_findings(path):
    """Return (findings dict id -> description, warnings, duplicate ids)."""
    findings = {}
    duplicates = []
    warnings = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = FINDING_RE.match(line)
            if not match:
                warnings.append(f"{path}:{lineno}: skipped, no 'ID:' shape: {line[:60]!r}")
                continue
            fid = match.group(1)
            if fid in findings:
                duplicates.append(fid)
            findings[fid] = line.split(":", 1)[1].strip()
    return findings, warnings, duplicates


def parse_tasks(path):
    """Return (tasks dict id -> set of covered ids, warnings, duplicate ids)."""
    tasks = {}
    duplicates = []
    warnings = []
    current = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            task_match = TASK_RE.match(raw)
            if task_match:
                current = task_match.group(1)
                if current in tasks:
                    duplicates.append(current)
                else:
                    tasks[current] = set()
                continue
            covers_match = COVERS_RE.search(raw)
            if covers_match:
                if current is None:
                    warnings.append(
                        f"{path}:{lineno}: Covers: line outside any task, ignored"
                    )
                    continue
                for fid in ID_RE.findall(covers_match.group(1)):
                    tasks[current].add(fid)
    return tasks, warnings, duplicates


def check(findings_path, tasks_path):
    """Run all checks. Returns a result dict (never raises on bad input)."""
    findings, f_warnings, f_duplicates = parse_findings(findings_path)
    tasks, t_warnings, t_duplicates = parse_tasks(tasks_path)

    covered = set()
    unknown = {}
    for tid, refs in tasks.items():
        for fid in refs:
            if fid in findings:
                covered.add(fid)
            else:
                unknown.setdefault(tid, sorted(r for r in refs if r not in findings))
    uncovered = sorted(set(findings) - covered)

    ok = not uncovered and not unknown and not t_duplicates and not f_duplicates
    return {
        "findings_total": len(findings),
        "tasks_total": len(tasks),
        "covered": sorted(covered),
        "uncovered": uncovered,
        "unknown_references": unknown,
        "duplicate_task_ids": sorted(set(t_duplicates)),
        "duplicate_finding_ids": sorted(set(f_duplicates)),
        "warnings": f_warnings + t_warnings,
        "pass": ok,
    }


def format_report(result, findings_path, tasks_path):
    """Human-readable report for a check() result dict."""
    lines = [
        f"Coverage check: {tasks_path} against {findings_path}",
        f"Findings: {result['findings_total']} total, "
        f"{len(result['covered'])} covered, {len(result['uncovered'])} uncovered",
        f"Tasks: {result['tasks_total']}",
    ]
    if result["uncovered"]:
        lines.append("Uncovered findings: " + ", ".join(result["uncovered"]))
    if result["unknown_references"]:
        for tid in sorted(result["unknown_references"]):
            lines.append(
                f"Unknown reference in {tid}: "
                + ", ".join(result["unknown_references"][tid])
            )
    if result["duplicate_task_ids"]:
        lines.append("Duplicate task IDs: " + ", ".join(result["duplicate_task_ids"]))
    if result["duplicate_finding_ids"]:
        lines.append(
            "Duplicate finding IDs: " + ", ".join(result["duplicate_finding_ids"])
        )
    for warning in result["warnings"]:
        lines.append("Warning: " + warning)
    lines.append(
        "PASS — every finding is covered"
        if result["pass"]
        else "FAIL — see the problems above"
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check a task list covers every audit finding."
    )
    parser.add_argument("findings", help="findings file, one 'ID: description' per line")
    parser.add_argument("tasks", help="task-list Markdown file with Covers: lines")
    parser.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = parser.parse_args(argv)

    try:
        findings, _, _ = parse_findings(args.findings)
    except OSError as exc:
        print(f"error: cannot read findings file: {exc}", file=sys.stderr)
        return 2
    if not findings:
        print(f"error: no findings parsed from {args.findings}", file=sys.stderr)
        return 2
    try:
        result = check(args.findings, args.tasks)
    except OSError as exc:
        print(f"error: cannot read task-list file: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_report(result, args.findings, args.tasks))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
