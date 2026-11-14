"""Whitespace and layout cleanup for OCR text.

Cleanup only: it never changes words. The rules, in the order
they run:

  1. strip trailing whitespace per line
  2. collapse runs of 2+ spaces inside a line to one space
  3. remove a space before punctuation (.,!?:;)
  4. join a wrapped line to the next ONLY when the line ends
     with a lowercase letter or a comma AND the next line
     starts with a lowercase letter (a conservative mid-sentence
     join; a wrapped paragraph chains line by line)
  5. collapse runs of 2+ blank lines to a single blank line,
     and strip leading/trailing blank lines

clean_text returns (cleaned_text, changes): changes is a list
of plain strings like "joined 4 wrapped lines", one per rule
that actually changed something, empty when nothing changed.
Cleaning is idempotent: clean(clean(x)) == clean(x).
"""

import re

_SPACE_BEFORE_PUNCT = re.compile(r" ([.,!?:;])")
_RUN_OF_SPACES = re.compile(r" {2,}")


def _counted(number, singular, plural):
    """'1 wrapped line' / '4 wrapped lines'."""
    if number == 1:
        return "%d %s" % (number, singular)
    return "%d %s" % (number, plural)


def clean_text(text):
    """Clean OCR text; return (cleaned_text, changes)."""
    if text == "":
        return "", []
    changes = []
    lines = text.split("\n")

    # 1. trailing whitespace per line.
    trimmed = 0
    stripped = []
    for line in lines:
        new = line.rstrip(" \t\r")
        if new != line:
            trimmed += 1
        stripped.append(new)
    lines = stripped
    if trimmed:
        changes.append("trimmed trailing whitespace on %s"
                       % _counted(trimmed, "line", "lines"))

    # 2. runs of 2+ spaces inside a line.
    runs = 0
    collapsed = []
    for line in lines:
        new, found = _RUN_OF_SPACES.subn(" ", line)
        runs += found
        collapsed.append(new)
    lines = collapsed
    if runs:
        changes.append("collapsed %s"
                       % _counted(runs, "run of extra spaces",
                                  "runs of extra spaces"))

    # 3. space before punctuation.
    fixed = 0
    depunctuated = []
    for line in lines:
        new, found = _SPACE_BEFORE_PUNCT.subn(r"\1", line)
        fixed += found
        depunctuated.append(new)
    lines = depunctuated
    if fixed:
        changes.append("fixed %s"
                       % _counted(fixed, "space before punctuation",
                                  "spaces before punctuation"))

    # 4. conservative wrapped-line join.
    joined = 0
    out = []
    for line in lines:
        if (out and out[-1] and line
                and (out[-1][-1].islower()
                     or out[-1].endswith(","))
                and line[0].islower()):
            out[-1] = out[-1] + " " + line
            joined += 1
        else:
            out.append(line)
    lines = out
    if joined:
        changes.append("joined %s"
                       % _counted(joined, "wrapped line",
                                  "wrapped lines"))

    # 5. blank lines: strip the ends, collapse runs to one.
    removed = 0
    while lines and lines[0] == "":
        lines.pop(0)
        removed += 1
    while lines and lines[-1] == "":
        lines.pop()
        removed += 1
    deduped = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run == 1:
                deduped.append(line)
            else:
                removed += 1
        else:
            blank_run = 0
            deduped.append(line)
    if removed:
        changes.append("removed %s"
                       % _counted(removed, "blank line",
                                  "blank lines"))
    return "\n".join(deduped), changes
