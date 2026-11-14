"""The flag piece of Repo Health Board: read a repos JSON file,
apply the health rules, and write flagged JSON plus the
plain-text board.

    python -m board.flag [--in FILE] [--out FILE] [--text FILE]

Reads any fetch output, including one made by hand: it only
needs the repos JSON shape (org, fetched_at, rate_limited,
rate_reset_at, repos as RepoHealth dicts). Writes flagged.json:

    {"org": ..., "fetched_at": ..., "rate_limited": ...,
     "rate_reset_at": ...,
     "rows": [{"health": {...},
               "flags": [{"kind": ..., "label": ...}],
               "suite": "has CI" | "no CI file" | "unknown"}],
     "counts": {"total": N, "flagged": N, "unchecked": N}}

A row is unchecked when its tree was not fetched (file_count
None). The text board is the same text board.export
format_board_text produces.

Exit codes: 0 ok; 2 bad input (missing file, bad JSON, wrong
shape). All messages are plain facts on stdout, no tracebacks.
"""

import argparse
import json
import os
import sys
import tempfile

from .export import format_board_text
from .flags import RepoHealth, compute_flags, suite_status
from .settings import (default_board_text_path,
                       default_flagged_path, default_repos_path)


def write_text_atomic(path, text):
    """Write text atomically: temp file + os.replace."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".board-flag-",
                               dir=parent or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_repos_json(path):
    """(data, error): the parsed repos JSON, or (None, message)
    when the file is missing, unreadable, or the wrong shape."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, "No such file: %s" % path
    except OSError as exc:
        return None, "Could not read %s: %s" % (path, exc)
    except ValueError:
        return None, "%s is not valid JSON." % path
    if not isinstance(data, dict) or not isinstance(
            data.get("repos"), list):
        return None, ("%s does not look like fetch output "
                      "(no repos list)." % path)
    return data, None


def build_flagged_json(data):
    """The flagged JSON shape plus the text board, from parsed
    repos JSON. Returns (flagged_dict, board_text)."""
    org = data.get("org") or "unknown"
    fetched_at = data.get("fetched_at")
    rows_with_flags = []
    rows = []
    flagged = 0
    unchecked = 0
    for entry in data["repos"]:
        if not isinstance(entry, dict):
            continue
        health = RepoHealth.from_dict(entry)
        flags = compute_flags(health)
        suite = suite_status(health)
        rows_with_flags.append((health, flags))
        rows.append({
            "health": health.to_dict(),
            "flags": [{"kind": flag.kind, "label": flag.label}
                      for flag in flags],
            "suite": suite,
        })
        if flags:
            flagged += 1
        if health.file_count is None:
            unchecked += 1
    flagged_json = {
        "org": org,
        "fetched_at": fetched_at,
        "rate_limited": bool(data.get("rate_limited")),
        "rate_reset_at": data.get("rate_reset_at"),
        "rows": rows,
        "counts": {"total": len(rows), "flagged": flagged,
                   "unchecked": unchecked},
    }
    text = format_board_text(rows_with_flags, org, fetched_at)
    return flagged_json, text


def build_parser():
    parser = argparse.ArgumentParser(
        prog="board-flag",
        description="Read a repos JSON file, apply the health "
                    "rules, and write flagged JSON plus the "
                    "plain-text board.")
    parser.add_argument("--in", dest="input_file", default=None,
                        help="repos JSON to read (default: "
                             "repos.json in the data dir)")
    parser.add_argument("--out", default=None,
                        help="flagged JSON to write (default: "
                             "flagged.json in the data dir)")
    parser.add_argument("--text", default=None,
                        help="text board to write (default: "
                             "board.txt in the data dir)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    in_path = args.input_file or default_repos_path()
    out_path = args.out or default_flagged_path()
    text_path = args.text or default_board_text_path()
    data, error = load_repos_json(in_path)
    if error is not None:
        print(error)
        return 2
    flagged_json, text = build_flagged_json(data)
    try:
        write_text_atomic(
            out_path,
            json.dumps(flagged_json, indent=2, sort_keys=True)
            + "\n")
        write_text_atomic(text_path, text)
    except OSError as exc:
        print("Could not write the flagged board: %s" % exc)
        return 2
    counts = flagged_json["counts"]
    print("Wrote %s and %s: %d repos, %d flagged, %d unchecked"
          % (out_path, text_path, counts["total"],
             counts["flagged"], counts["unchecked"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
