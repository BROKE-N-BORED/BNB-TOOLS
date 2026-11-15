#!/usr/bin/env python3
"""tree-repo-sync-check (BNB-TOOLS T33): is the local tree what the repo ships?

Compares a local directory against a public GitHub repo, file by
file, using git blob SHAs. It reports three kinds of drift:

  differing           the file exists in both, with different content
  missing on remote   the file is in the local tree but not on remote
                      (extra local files: fixes or files never pushed)
  missing locally     the file is on remote but not in the local tree

Exit codes: 0 clean, 1 differences found, 2 could not check
(no network, repo or branch not found, rate limited, bad input).
Errors are plain words naming the missing thing, never a traceback.

Public repos only. This tool sends no auth of any kind: no token,
no login, no Authorization header. A private repo answers 404 or
403 to an unauthenticated request, and this tool reports that as
"could not check" rather than guessing.

How the comparison works: the remote tree comes from one GitHub
API call (GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1).
Each local file is hashed the way git hashes a blob
(SHA-1 of "blob <length>" plus a NUL byte plus the bytes), so the
local and remote SHAs compare directly, with no git binary needed.
Only committed content is compared on the remote side; on the local
side the tree on disk is compared, so untracked and ignored files
show up as missing on remote. That is by design: the question this
tool answers is "does the repo ship what is on this disk", not
"is the git index clean". The .git directory itself is skipped.
File modes are not compared (a blob SHA does not cover the exec
bit), and submodule entries on remote are ignored.

Rate limits: the tool makes exactly one API request. If GitHub
answers that the rate limit is reached, the tool stops cleanly,
names the reset time, and never retries.

Usage:
  python3 tree_repo_sync_check.py <local-dir> <owner/repo>
      [--branch BRANCH] [--json] [--timeout SECONDS]
      [--debug-report PATH]
  python3 tree_repo_sync_check.py debug-report [--out PATH]
  python3 tree_repo_sync_check.py --help

The --api-base flag (and the TREE_SYNC_API_BASE environment
variable) point the tool at a different GitHub API base URL.
They exist for the test suite, which runs against a local fake
GitHub server. Do not use them for real checks.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
APP_SLUG = "tree-repo-sync-check"
DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30
REPORT_EMAIL = "broke.n.bored.studio@gmail.com"

try:
    from debug_log import DebugLogger
except ImportError:  # the script copied without its debug_log.py
    DebugLogger = None


class CheckError(Exception):
    """A plain-words failure: the check could not run or finish."""


class RateLimited(CheckError):
    """GitHub said the rate limit is reached. Never retried."""

    def __init__(self, reset_text):
        self.reset_text = reset_text  # human-readable time, or None
        if reset_text:
            message = ("GitHub API rate limit reached. No retry was "
                       "made. The limit resets at %s. Try again "
                       "after that time." % reset_text)
        else:
            message = ("GitHub API rate limit reached. No retry was "
                       "made. GitHub did not give a reset time. "
                       "Try again later.")
        super().__init__(message)


# ---------------------------------------------------------------- hashing

def blob_sha(data):
    """The git blob SHA of bytes: SHA-1 of the blob header + data.

    Identical to `git hash-object` for the same bytes, with no git
    binary needed. The test suite cross-checks this against the
    real git hash-object when git is installed.
    """
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data).hexdigest()


def collect_local(local_dir):
    """{relative path: blob SHA} for every file under local_dir.

    Skips .git directories at any depth. A symlink is hashed by
    its target path, the way git stores it (the blob content of
    a symlink is the target). An unreadable file is an error
    naming the file: a silent skip would hide drift.
    """
    found = {}
    for dirpath, dirnames, filenames in os.walk(local_dir):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, local_dir)
            try:
                if os.path.islink(full):
                    data = os.readlink(full).encode("utf-8")
                else:
                    with open(full, "rb") as handle:
                        data = handle.read()
            except OSError as exc:
                raise CheckError("cannot read local file %s: %s"
                                 % (rel, exc))
            found[rel] = blob_sha(data)
    return found


# ---------------------------------------------------------------- fetching

def _reset_time_text(headers):
    """Human-readable UTC reset time from the rate-limit headers.

    Returns None when the header is missing or unparsable: the
    caller says so plainly instead of inventing a time.
    """
    raw = headers.get("X-RateLimit-Reset")
    if not raw:
        return None
    try:
        when = datetime.datetime.fromtimestamp(
            int(raw), tz=datetime.timezone.utc)
    except (ValueError, OverflowError):
        return None
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_rate_limit(status, headers, payload):
    """True when a response means the rate limit, not a plain deny.

    GitHub signals it two ways: a 403 with X-RateLimit-Remaining
    at 0, or a message saying the rate limit was exceeded. Either
    counts. A plain 403 (a private repo, a forbidden endpoint)
    is not a rate limit and is reported differently.
    """
    if status != 403:
        return False
    if headers.get("X-RateLimit-Remaining") == "0":
        return True
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("message", ""))
    return "rate limit" in message.lower()


def fetch_remote_tree(api_base, owner, repo, branch, timeout):
    """{relative path: blob SHA} for the remote branch, one request.

    Only blob entries are kept: tree entries are directories and
    commit entries are submodules, neither of which this tool
    compares. Raises CheckError (or RateLimited) with a plain
    message on any failure. Makes exactly one request, never
    retries, sends no Authorization header.
    """
    url = "%s/repos/%s/%s/git/trees/%s?recursive=1" % (
        api_base.rstrip("/"),
        urllib.parse.quote(owner, safe=""),
        urllib.parse.quote(repo, safe=""),
        urllib.parse.quote(branch, safe=""))
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "%s/%s" % (APP_SLUG, VERSION)})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            headers = resp.headers
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if _is_rate_limit(exc.code, exc.headers, payload):
            raise RateLimited(_reset_time_text(exc.headers))
        if exc.code == 404:
            raise CheckError(
                "repo or branch not found on GitHub: %s/%s "
                "(branch %s). Check the owner, repo name, and "
                "branch. Private repos also answer this way: "
                "this tool only checks public repos."
                % (owner, repo, branch))
        if exc.code == 403:
            raise CheckError(
                "GitHub refused the request for %s/%s (HTTP 403). "
                "This tool only checks public repos and sends no "
                "login: a private repo answers this way."
                % (owner, repo))
        raise CheckError(
            "GitHub answered with an error for %s/%s (HTTP %s)."
            % (owner, repo, exc.code))
    except urllib.error.URLError as exc:
        raise CheckError(
            "could not reach GitHub (%s). Check the network "
            "connection and try again." % exc.reason)
    except (TimeoutError, OSError) as exc:
        raise CheckError(
            "could not reach GitHub (%s). Check the network "
            "connection and try again." % exc)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CheckError(
            "GitHub returned a reply that is not valid JSON for "
            "%s/%s. Try again later." % (owner, repo))
    if payload.get("truncated"):
        raise CheckError(
            "the remote tree for %s/%s is too large: GitHub "
            "truncated the listing, so the comparison cannot be "
            "trusted. This tool cannot check repos that large."
            % (owner, repo))
    entries = payload.get("tree")
    if not isinstance(entries, list):
        raise CheckError(
            "GitHub returned an unexpected reply for %s/%s (no "
            "tree in the reply). Try again later." % (owner, repo))
    remote = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        path = entry.get("path")
        sha = entry.get("sha")
        if isinstance(path, str) and isinstance(sha, str):
            remote[path] = sha
    return remote


# ---------------------------------------------------------------- comparing

def compare(local, remote):
    """(differing, missing_on_remote, missing_locally), each sorted.

    differing: in both, different blob SHA.
    missing_on_remote: in the local tree, not on remote.
    missing_locally: on remote, not in the local tree.
    """
    differing = sorted(path for path in local
                       if path in remote and local[path] != remote[path])
    missing_on_remote = sorted(path for path in local
                               if path not in remote)
    missing_locally = sorted(path for path in remote
                             if path not in local)
    return differing, missing_on_remote, missing_locally


# ---------------------------------------------------------------- debug log

def _github_status(api_base):
    """GitHub API status for the debug report (short timeout)."""
    try:
        request = urllib.request.Request(
            api_base.rstrip("/") + "/rate_limit",
            headers={"User-Agent": "%s/%s" % (APP_SLUG, VERSION)})
        with urllib.request.urlopen(request, timeout=2) as resp:
            return "reachable (HTTP %s)" % resp.status
    except urllib.error.HTTPError as exc:
        return "reachable but errored (HTTP %s)" % exc.code
    except Exception as exc:
        return "not reachable (%s)" % exc


def make_logger(api_base, log_dir):
    """The T21 debug log layer, wired to this app.

    Settings: the app version and the API base (no secrets ever:
    this tool has no credentials). Services: the GitHub API, the
    one service the app depends on. The log dir is a temp dir
    owned by the caller, so no logs/ directory is left behind.
    """
    if DebugLogger is None:
        raise CheckError(
            "debug report needs debug_log.py next to this script; "
            "it is missing.")
    logger = DebugLogger(APP_SLUG, VERSION, log_dir=log_dir)
    logger.set_setting("app_version", VERSION)
    logger.set_setting("api_base", api_base)
    logger.register_service("GitHub API",
                            lambda: _github_status(api_base))
    return logger


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        try:
            handler.close()
        finally:
            logger.logger.removeHandler(handler)


# ---------------------------------------------------------------- output

def print_human(result):
    """The plain-words report on stdout."""
    print("Checking %s against %s (%s)..."
          % (result["local_dir"], result["repo"], result["branch"]))
    if result["status"] == "clean":
        print("OK: local tree matches the remote tree (%d files)."
              % result["remote_files"])
        return
    differing = result["differing"]
    missing_on_remote = result["missing_on_remote"]
    missing_locally = result["missing_locally"]
    print("DIFFERENCES FOUND: %d differing, %d missing on remote, "
          "%d missing locally."
          % (len(differing), len(missing_on_remote),
             len(missing_locally)))
    if differing:
        print("Differing (%d):" % len(differing))
        for path in differing:
            print("  %s" % path)
    if missing_on_remote:
        print("Missing on remote (extra local files) (%d):"
              % len(missing_on_remote))
        for path in missing_on_remote:
            print("  %s" % path)
    if missing_locally:
        print("Missing locally (only on remote) (%d):"
              % len(missing_locally))
        for path in missing_locally:
            print("  %s" % path)


def print_json(result):
    """The machine-readable report on stdout."""
    print(json.dumps(result, indent=2, sort_keys=True))


# ---------------------------------------------------------------- commands

def _api_base(args):
    """Flag wins, then the environment, then the real GitHub API."""
    if getattr(args, "api_base", None):
        return args.api_base
    return os.environ.get("TREE_SYNC_API_BASE", DEFAULT_API_BASE)


def _parse_repo(text):
    """(owner, repo) or a plain-words CheckError."""
    parts = text.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise CheckError(
            "repo must look like owner/repo, for example "
            "BROKE-N-BORED/BNB-PLUGINS. Got: %s" % text)
    return parts[0], parts[1]


def cmd_check(args):
    """Compare one local dir against one remote branch.

    Exit 0 clean, 1 differences found, 2 could not check.
    """
    local_dir = os.path.abspath(args.local_dir)
    logger = None
    tmp = None
    try:
        if args.debug_report:
            try:
                tmp = tempfile.TemporaryDirectory(prefix="tree-sync.")
                logger = make_logger(_api_base(args), tmp.name)
            except (CheckError, OSError) as exc:
                # A missing debug layer must not fail the check
                # itself: warn, and run the check without a report.
                print("warning: debug report unavailable (%s)"
                      % exc, file=sys.stderr)
                logger = None
            else:
                logger.install_crash_handler()
                logger.action("check started for %s against %s"
                              % (local_dir, args.repo))
        if not os.path.isdir(local_dir):
            raise CheckError("local directory not found: %s"
                             % local_dir)
        owner, repo = _parse_repo(args.repo)
        api_base = _api_base(args)
        if logger is not None:
            logger.action("fetching remote tree for %s/%s (%s)"
                          % (owner, repo, args.branch))
        remote = fetch_remote_tree(api_base, owner, repo,
                                   args.branch, args.timeout)
        if logger is not None:
            logger.action("remote tree has %d files" % len(remote))
            logger.action("hashing local tree at %s" % local_dir)
        local = collect_local(local_dir)
        differing, missing_on_remote, missing_locally = compare(
            local, remote)
        status = ("clean" if not differing and not missing_on_remote
                  and not missing_locally else "differences")
        result = {
            "status": status,
            "repo": "%s/%s" % (owner, repo),
            "branch": args.branch,
            "local_dir": local_dir,
            "remote_files": len(remote),
            "local_files": len(local),
            "differing": differing,
            "missing_on_remote": missing_on_remote,
            "missing_locally": missing_locally,
        }
        if logger is not None:
            logger.action("check finished: %s" % status)
        if args.json:
            print_json(result)
        else:
            print_human(result)
        return 0 if status == "clean" else 1
    except CheckError as exc:
        if logger is not None:
            logger.error("check failed: %s", exc)
        if args.json:
            result = {
                "status": "error",
                "repo": args.repo,
                "branch": args.branch,
                "local_dir": local_dir,
                "error": str(exc),
                "rate_limit_reset": (
                    exc.reset_text
                    if isinstance(exc, RateLimited) else None),
            }
            print_json(result)
        else:
            print("error: %s" % exc, file=sys.stderr)
        return 2
    finally:
        if logger is not None and args.debug_report:
            try:
                path = logger.generate_report(args.debug_report)
                print("debug report written to %s" % path,
                      file=sys.stderr)
            except OSError as exc:
                print("warning: could not write debug report to "
                      "%s (%s)" % (args.debug_report, exc),
                      file=sys.stderr)
            _close_logger(logger)
        if tmp is not None:
            tmp.cleanup()


def cmd_debug_report(args):
    """Write a debug report and print its path. Exit 0."""
    if args.out is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        args.out = ("debug-report-%s-%s.txt" % (APP_SLUG, stamp))
    try:
        with tempfile.TemporaryDirectory(prefix="tree-sync.") as tmp:
            logger = make_logger(_api_base(args), tmp)
            try:
                path = logger.generate_report(args.out)
            finally:
                _close_logger(logger)
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: could not write debug report to %s (%s)"
              % (args.out, exc), file=sys.stderr)
        return 2
    print("Debug report written to %s" % path)
    print("Send it to %s if something is broken." % REPORT_EMAIL)
    return 0


# ---------------------------------------------------------------- CLI

def build_check_parser():
    parser = argparse.ArgumentParser(
        prog="tree_repo_sync_check.py",
        description="Compare a local directory against a public "
                    "GitHub repo, file by file, using git blob "
                    "SHAs. Reports files that differ, files "
                    "missing on remote (extra local files), and "
                    "files missing locally. Public repos only: "
                    "this tool sends no login and no token. "
                    "Exit 0 clean, 1 differences found, "
                    "2 could not check.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + VERSION)
    parser.add_argument("local_dir", metavar="LOCAL-DIR",
                        help="local directory to compare")
    parser.add_argument("repo", metavar="OWNER/REPO",
                        help="public GitHub repo, for example "
                             "BROKE-N-BORED/BNB-PLUGINS")
    parser.add_argument("--branch", default="main",
                        help="remote branch to compare against "
                             "(default: main)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON (also for "
                             "errors, which otherwise go to stderr)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="seconds to wait for the GitHub reply "
                             "(default: %d)" % DEFAULT_TIMEOUT)
    parser.add_argument("--api-base", default=None,
                        help="GitHub API base URL (for tests only; "
                             "default: https://api.github.com, or "
                             "TREE_SYNC_API_BASE when set)")
    parser.add_argument("--debug-report", default=None,
                        metavar="PATH",
                        help="also write a debug report to PATH "
                             "(T21 debug log layer; the path is "
                             "printed on stderr so --json output "
                             "stays clean)")
    return parser


def build_debug_parser():
    parser = argparse.ArgumentParser(
        prog="tree_repo_sync_check.py debug-report",
        description="Write a debug report (T21 debug log layer) "
                    "and print its path.")
    parser.add_argument("--out", default=None,
                        help="report path (default: "
                             "debug-report-tree-repo-sync-check-"
                             "<date>.txt in the current directory)")
    parser.add_argument("--api-base", default=None,
                        help="GitHub API base URL (for tests only)")
    return parser


def main(argv=None):
    """Dispatch: `debug-report` is a subcommand, anything else is
    a check. --help exits 0. No traceback ever reaches the user:
    unexpected errors are reported in plain words, exit 2."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        if argv and argv[0] == "debug-report":
            args = build_debug_parser().parse_args(argv[1:])
            return cmd_debug_report(args)
        args = build_check_parser().parse_args(argv)
        return cmd_check(args)
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 2
    except KeyboardInterrupt:
        print("error: stopped by the user.", file=sys.stderr)
        return 2
    except Exception as exc:  # never a traceback, per the spec
        print("error: the check failed unexpectedly (%s). "
              "Run again with --debug-report PATH and send the "
              "report to %s if it keeps happening."
              % (exc, REPORT_EMAIL), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
