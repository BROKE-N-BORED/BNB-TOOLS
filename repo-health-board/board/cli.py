"""Command line for Repo Health Board.

    board-cli --help
    board-cli refresh [--org X]
    board-cli show
    board-cli export [--out FILE]
    board-cli debug-report

The CLI works with no Qt installed and no display. Refresh runs
the chain in-process: board.fetch pulls fresh data from GitHub
and writes repos.json, then board.flag reads it and writes the
flagged board; refresh then prints the text board. Show prints
the text board from the last refresh. Refresh talks to the live
api.github.com; the BOARD_BASE_URL environment variable
overrides the API base URL (a test hook, so the suite can point
the CLI at the local fake server).
"""

import argparse
import os
import sys

from . import __version__
from . import fetch as fetch_piece
from . import flag as flag_piece
from .api import ApiError, GitHubClient
from .cache import BoardCache
from .debug_log import DebugLogger
from .export import format_board_text
from .flags import RepoHealth, compute_flags
from .settings import Settings, default_board_text_path, log_dir

APP_NAME = "Repo Health Board"
APP_SLUG = "repo-health-board"
REPORT_EMAIL = "broke.n.bored.studio@gmail.com"


def _api_base_url():
    return fetch_piece.resolve_base_url(None)


def _github_status():
    """GitHub API status for the debug report (short timeout)."""
    try:
        client = GitHubClient(base_url=_api_base_url(), timeout=2)
        status, _payload, _headers = client.get_json("/rate_limit")
        return "reachable (HTTP %s)" % status
    except ApiError as exc:
        return "reachable but errored (%s)" % exc.message
    except Exception as exc:
        return "not reachable (%s)" % exc


def make_logger():
    """The debug log layer, wired to this app.

    Settings: the app version and the org, no secrets ever.
    Services: the GitHub API, the one service the app depends on.
    """
    logger = DebugLogger(APP_SLUG, __version__, log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.set_setting("app_version", __version__)
    logger.set_setting("org", Settings().org)
    logger.register_service("GitHub API", _github_status)
    return logger


def _load_cached_rows(settings):
    """(cache, rows) from the cache file, rows sorted by name."""
    cache = BoardCache(settings.cache_file())
    rows = []
    for name in cache.repo_names():
        health = RepoHealth.from_dict(cache.get_repo(name))
        health.from_cache = True
        rows.append(health)
    return cache, rows


def _board_text(cache, rows, org):
    rows_with_flags = [(row, compute_flags(row)) for row in rows]
    return format_board_text(rows_with_flags, org,
                             cache.fetched_at)


def cmd_refresh(args):
    """Run the chain in-process (fetch then flag) and print the
    board. The fetch exit code propagates: 1 when the fetch was
    partial (the board still prints), 2 when the fetch could not
    run at all (flag does not run, nothing prints)."""
    settings = Settings()
    org = args.org or settings.org
    logger = make_logger()
    logger.install_crash_handler()
    logger.action("refresh started for org %s" % org)
    fetch_code = fetch_piece.main(["--org", org])
    if fetch_code == 2:
        logger.warning("refresh could not run (fetch exit 2)")
        return 2
    flag_code = flag_piece.main([])
    if flag_code != 0:
        logger.warning("refresh flag step failed (exit %d)"
                       % flag_code)
        return flag_code
    text_path = default_board_text_path()
    try:
        with open(text_path, encoding="utf-8") as fh:
            print(fh.read(), end="")
    except OSError:
        print("Board text is missing. Run board-cli refresh again.")
        return 1
    cache = BoardCache(settings.cache_file())
    settings.org = org
    settings.last_refresh = cache.fetched_at
    settings.save()
    logger.action("refresh finished (fetch exit %d)" % fetch_code)
    return fetch_code


def cmd_show(args):
    text_path = default_board_text_path()
    try:
        with open(text_path, encoding="utf-8") as fh:
            print(fh.read(), end="")
    except OSError:
        print("No cached data yet. Run board-cli refresh first.")
    return 0


def cmd_export(args):
    settings = Settings()
    cache, rows = _load_cached_rows(settings)
    if not rows:
        print("No cached data yet. Run board-cli refresh first.",
              file=sys.stderr)
        return 1
    org = cache.org or settings.org
    text = _board_text(cache, rows, org)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("Board written to %s" % args.out)
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
        prog="board-cli",
        description="Repo Health Board: check the health of every "
                    "repo in an org.")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="command")
    refresh = sub.add_parser(
        "refresh",
        help="fetch fresh health data from GitHub and print the "
             "board")
    refresh.add_argument("--org", default=None,
                         help="org to check (default: the saved org)")
    sub.add_parser("show",
                   help="print the board from the last refresh")
    export = sub.add_parser(
        "export", help="write the board as text")
    export.add_argument("--out", default=None,
                        help="file to write (default: print to stdout)")
    sub.add_parser("debug-report",
                   help="write a debug report and print its path")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "refresh":
        return cmd_refresh(args)
    if args.command == "show":
        return cmd_show(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "debug-report":
        return cmd_debug_report(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
