"""Plain-text board export for Repo Health Board.

No em-dashes anywhere in the output: copy is plain facts.
"""

from .flags import compute_flags  # noqa: F401  (re-exported for callers)


def format_repo_line(health, flags):
    """One line per repo:

    name | last commit YYYY-MM-DD or "unknown" | N files or
    "unknown" | release tag or "none" | flags comma-separated
    or "ok"
    """
    if health.last_commit_date:
        date = health.last_commit_date[:10]
    else:
        date = "unknown"
    if health.file_count is not None:
        files = "%d files" % health.file_count
    else:
        files = "unknown"
    release = health.latest_release_tag or "none"
    if flags:
        flag_text = ", ".join(flag.label for flag in flags)
    else:
        flag_text = "ok"
    return "%s | %s | %s | %s | %s" % (health.name, date, files,
                                       release, flag_text)


def format_board_text(rows_with_flags, org, fetched_at):
    """The whole board as text: a header line with the org and the
    fetch date, one line per repo, and a footer with counts."""
    stamp = fetched_at or "unknown"
    lines = ["Repo Health Board: %s (fetched %s)" % (org, stamp)]
    flagged = 0
    for health, flags in rows_with_flags:
        lines.append(format_repo_line(health, flags))
        if flags:
            flagged += 1
    total = len(rows_with_flags)
    lines.append("%d repos, %d flagged, %d ok"
                 % (total, flagged, total - flagged))
    return "\n".join(lines) + "\n"
