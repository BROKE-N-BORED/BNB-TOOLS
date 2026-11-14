"""The fetch piece of Repo Health Board: pull org repo data from
the public GitHub API and write repos JSON.

    python -m board.fetch [--org X] [--out FILE] [--base-url URL]
                          [--cache FILE] [--timeout N]

One small chainable piece: fetch writes repos.json, board.flag
reads it and writes the flagged board. No authentication, ever:
the board reads public repos, which need no token.

Exit codes: 0 ok; 1 partial (rate-limited or per-repo errors,
repos JSON still written with what was fetched); 2 could not
run (org not found, network down, no repos listed). All messages
are plain facts on stdout, no tracebacks.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from .api import GitHubClient
from .cache import BoardCache
from .refresh import refresh_org
from .settings import Settings, default_repos_path

DEFAULT_BASE_URL = "https://api.github.com"
BASE_URL_ENV = "BOARD_BASE_URL"
# The older hook, kept so the existing CLI tests still work.
LEGACY_BASE_URL_ENV = "REPO_HEALTH_BOARD_API_URL"


def resolve_base_url(cli_value):
    """The API base URL: --base-url wins, then BOARD_BASE_URL,
    then the legacy REPO_HEALTH_BOARD_API_URL, then the default."""
    if cli_value:
        return cli_value
    return (os.environ.get(BASE_URL_ENV)
            or os.environ.get(LEGACY_BASE_URL_ENV)
            or DEFAULT_BASE_URL)


def write_json_atomic(path, data):
    """Write JSON atomically: temp file + os.replace."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".board-repos-",
                               dir=parent or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build_repos_json(org, result, fetched_at):
    """The repos JSON shape (see the module docstring of
    board.flag for the shape the next piece reads)."""
    return {
        "org": org,
        "fetched_at": fetched_at,
        "rate_limited": result.rate_limited,
        "rate_reset_at": result.rate_reset_at,
        "repos": [row.to_dict() for row in result.rows],
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="board-fetch",
        description="Fetch repo health data for an org from the "
                    "public GitHub API (no auth) and write "
                    "repos.json.")
    parser.add_argument("--org", default=None,
                        help="org to check (default: the saved org, "
                             "else BROKE-N-BORED)")
    parser.add_argument("--out", default=None,
                        help="repos JSON to write (default: "
                             "repos.json in the data dir)")
    parser.add_argument("--base-url", default=None,
                        help="GitHub API base URL (default: "
                             "https://api.github.com, or the "
                             "BOARD_BASE_URL env var)")
    parser.add_argument("--cache", default=None,
                        help="cache file (default: cache.json in "
                             "the data dir)")
    parser.add_argument("--timeout", type=int, default=15,
                        help="request timeout in seconds "
                             "(default: 15)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    settings = Settings()
    org = args.org or settings.org
    out_path = args.out or default_repos_path()
    cache_path = args.cache or settings.cache_file()
    base_url = resolve_base_url(args.base_url)
    client = GitHubClient(base_url=base_url, timeout=args.timeout)
    cache = BoardCache(cache_path)

    def progress(kind, current, total, name):
        if kind == "repo":
            print("Checking %d of %d: %s" % (current, total, name))

    result = refresh_org(client, org, cache, progress_cb=progress)
    fetched_at = cache.fetched_at or datetime.now(
        timezone.utc).isoformat(timespec="seconds")

    if result.rate_limited:
        try:
            write_json_atomic(
                out_path, build_repos_json(org, result, fetched_at))
        except OSError as exc:
            print("Could not write %s: %s" % (out_path, exc))
            return 2
        if result.rate_reset_at:
            reset = datetime.fromtimestamp(
                result.rate_reset_at, tz=timezone.utc)
            print("Rate limit reached: try again after %s UTC."
                  % reset.strftime("%Y-%m-%d %H:%M"))
        else:
            print("Rate limit reached: try again later.")
        print("Fetched %d repos: %d fresh, %d cached, "
              "%d unchecked" % (len(result.rows),
                                result.fresh_count,
                                result.cached_count,
                                result.unchecked_count))
        for error in result.errors:
            if "rate limit" not in error.lower():
                print("Error: %s" % error)
        return 1

    if not result.rows:
        if result.errors:
            for error in result.errors:
                print(error)
        else:
            print("No repos found in org %s." % org)
        return 2

    try:
        write_json_atomic(
            out_path, build_repos_json(org, result, fetched_at))
    except OSError as exc:
        print("Could not write %s: %s" % (out_path, exc))
        return 2
    print("Fetched %d repos: %d fresh, %d cached, %d unchecked"
          % (len(result.rows), result.fresh_count,
             result.cached_count, result.unchecked_count))
    if result.errors:
        for error in result.errors:
            print("Error: %s" % error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
