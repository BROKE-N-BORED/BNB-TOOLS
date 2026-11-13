#!/usr/bin/env python3
"""List a GitHub account's repos live and write an audit queue file.

Starting point for the org-repo-audit-queue skill: fetch the live repo
list for a GitHub user or org, sort it by creation date (oldest
first), and write it out as JSON inventory + a markdown queue file
with one repo per line and a state column.

Also diffs a fresh listing against a saved inventory: reports repos
that are new since the last listing, repos that disappeared, and repos
whose description, topics, visibility, or last-push date changed —
because metadata changes during the day and an older listing goes
stale (OpenRealism's and FRIDAY's descriptions both changed on
2026-11-12 between the morning listing and the evening audits).

Usage:

    python3 org_inventory.py BROKE-N-BORED
    python3 org_inventory.py BROKE-N-BORED --json inventory.json --queue queue.md
    python3 org_inventory.py BROKE-N-BORED --diff inventory-old.json
    python3 org_inventory.py some-org --type org --newest-first

Auth: none needed for public repos. A token via the GITHUB_TOKEN
environment variable only (never a CLI flag) lists private repos too
and raises the rate limit from 60 to 5,000 requests/hour. Without a
token, private repos are invisible — the output says so plainly
instead of claiming the account has no private repos.

A network failure or rate limit is reported as "could not check"
(exit 1), never as an empty repo list.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
USER_AGENT = "bnb-org-repo-inventory"
PER_PAGE = 100


class InventoryError(Exception):
    """A plain-language failure: network, rate limit, or bad input."""


def _headers():
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _get_json(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise InventoryError("not found: %s" % url)
        if exc.code in (403, 429):
            raise InventoryError(
                "GitHub rate limit hit (HTTP %d). Wait, or set "
                "GITHUB_TOKEN for 5,000 requests/hour." % exc.code)
        raise InventoryError("GitHub answered HTTP %d for %s"
                             % (exc.code, url))
    except urllib.error.URLError as exc:
        raise InventoryError("could not reach api.github.com: %s"
                             % exc.reason)
    except ValueError:
        raise InventoryError("GitHub returned unparseable JSON for %s"
                             % url)


def _has_next_page(headers):
    link = headers.get("Link") or ""
    return 'rel="next"' in link


def fetch_repos(account, account_type=None):
    """Live repo list for a GitHub user or org.

    account_type is "user", "org", or None (auto-detect: try org
    first, fall back to user on 404 — BROKE-N-BORED is a user
    account, not an org). Returns (repos, detected_type). Each repo
    is the trimmed dict written to the inventory.
    """
    types = [account_type] if account_type else ["org", "user"]
    last_error = None
    for kind in types:
        try:
            return _fetch_pages(account, kind), kind
        except InventoryError as exc:
            last_error = exc
            if "not found" not in str(exc):
                raise
    raise InventoryError(
        "no GitHub user or org named %r exists (tried %s)"
        % (account, " and ".join(types)))


def _fetch_pages(account, kind):
    repos = []
    page = 1
    while True:
        url = ("%s/%ss/%s/repos?per_page=%d&page=%d"
               % (API, kind, account, PER_PAGE, page))
        data, headers = _get_json(url)
        for entry in data:
            repos.append(trim_repo(entry))
        if not _has_next_page(headers) or len(data) < PER_PAGE:
            break
        page += 1
    return repos


def trim_repo(entry):
    """The fields the queue cares about, nothing more."""
    return {
        "name": entry.get("name"),
        "full_name": entry.get("full_name"),
        "description": entry.get("description") or "",
        "private": bool(entry.get("private")),
        "created_at": entry.get("created_at"),
        "pushed_at": entry.get("pushed_at"),
        "size_kb": entry.get("size"),
        "language": entry.get("language"),
        "topics": sorted(entry.get("topics") or []),
        "default_branch": entry.get("default_branch"),
        "open_issues": entry.get("open_issues_count"),
        "html_url": entry.get("html_url"),
    }


def sort_repos(repos, newest_first=False):
    return sorted(repos, key=lambda r: (r["created_at"] or "", r["name"]),
                  reverse=newest_first)


def render_queue(repos, account, newest_first=False, token_used=False):
    """Markdown queue file: one repo per line, oldest first by
    default, with a state column the audit cycle updates."""
    order = "newest first" if newest_first else "oldest first"
    lines = [
        "# %s repo audit queue" % account,
        "",
        "One repo at a time, in this order (%s by creation date). "
        "Each report covers: features, functions, strengths, "
        "weaknesses, gaps, UI flaws, innovation suggestions, design "
        "suggestions, anything new / needing improvement / update / "
        "upgrade." % order,
        "",
        "Rules:",
        "- Audit ONLY repos that exist live on GitHub.",
        "- Read-only audit; no pushes, releases, or edits unless "
        "the owner asks for a specific repo.",
        "- Verify descriptions/topics live at delivery time — "
        "metadata changes during the day.",
        "",
    ]
    if not token_used:
        lines += [
            "Note: listed WITHOUT a token, so private repos are NOT "
            "in this list. Set GITHUB_TOKEN and re-run to include "
            "them.",
            "",
        ]
    for i, repo in enumerate(repos, 1):
        private = ", private" if repo["private"] else ""
        created = (repo["created_at"] or "?")[:10]
        desc = repo["description"].strip()
        desc = (" — " + desc) if desc else ""
        lines.append("%d. %s (%s%s) — PENDING%s"
                     % (i, repo["name"], created, private, desc))
    lines.append("")
    return "\n".join(lines)


def diff_inventories(old, new):
    """Compare two inventories. Returns (added, removed, changed).

    changed entries are (name, {field: (old, new)}) for description,
    topics, private, and pushed_at.
    """
    old_by_name = {r["name"]: r for r in old}
    new_by_name = {r["name"]: r for r in new}
    added = sorted(set(new_by_name) - set(old_by_name))
    removed = sorted(set(old_by_name) - set(new_by_name))
    changed = []
    watched = ("description", "topics", "private", "pushed_at")
    for name in sorted(set(old_by_name) & set(new_by_name)):
        diffs = {}
        for field in watched:
            if old_by_name[name].get(field) != new_by_name[name].get(field):
                diffs[field] = (old_by_name[name].get(field),
                                new_by_name[name].get(field))
        if diffs:
            changed.append((name, diffs))
    return added, removed, changed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List a GitHub account's repos live and write an "
        "audit queue file.")
    parser.add_argument("account", help="GitHub user or org name")
    parser.add_argument("--type", dest="account_type",
                        choices=["user", "org"], default=None,
                        help="account type (default: auto-detect)")
    parser.add_argument("--newest-first", action="store_true",
                        help="sort newest first instead of oldest first")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="write the JSON inventory to this file")
    parser.add_argument("--queue", dest="queue_path", default=None,
                        help="write the markdown queue file to this file")
    parser.add_argument("--diff", dest="diff_path", default=None,
                        help="compare against a saved inventory JSON "
                        "and report new/removed/changed repos")
    args = parser.parse_args(argv)

    try:
        repos, detected = fetch_repos(args.account, args.account_type)
    except InventoryError as exc:
        print("could not check: %s" % exc, file=sys.stderr)
        return 1
    repos = sort_repos(repos, newest_first=args.newest_first)
    token_used = bool(os.environ.get("GITHUB_TOKEN"))
    print("%d repos live under %s (%s)%s"
          % (len(repos), args.account, detected,
             "" if token_used else " — public only, no token"))
    for repo in repos:
        print("  %-40s %s%s"
              % (repo["name"], (repo["created_at"] or "?")[:10],
                 " (private)" if repo["private"] else ""))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump({"account": args.account, "type": detected,
                       "token_used": token_used, "repos": repos},
                      fh, indent=2)
            fh.write("\n")
        print("inventory written to %s" % args.json_path)
    if args.queue_path:
        with open(args.queue_path, "w", encoding="utf-8") as fh:
            fh.write(render_queue(repos, args.account,
                                  newest_first=args.newest_first,
                                  token_used=token_used))
        print("queue written to %s" % args.queue_path)
    if args.diff_path:
        try:
            with open(args.diff_path, encoding="utf-8") as fh:
                old = json.load(fh)["repos"]
        except (OSError, ValueError, KeyError) as exc:
            print("could not read diff inventory %s: %s"
                  % (args.diff_path, exc), file=sys.stderr)
            return 1
        added, removed, changed = diff_inventories(old, repos)
        print("diff vs %s:" % args.diff_path)
        print("  new repos (%d): %s"
              % (len(added), ", ".join(added) or "none"))
        print("  removed repos (%d): %s"
              % (len(removed), ", ".join(removed) or "none"))
        print("  changed repos (%d):" % len(changed))
        for name, diffs in changed:
            for field, (before, after) in sorted(diffs.items()):
                print("    %s: %s: %r -> %r" % (name, field, before, after))
    return 0


if __name__ == "__main__":
    sys.exit(main())
