#!/usr/bin/env python3
"""Smoke test for org_inventory.py.

Part 1 (no network): canned-response parsing, sorting, queue
rendering, and diff detection.
Part 2 (live, needs api.github.com): list BROKE-N-BORED, assert the
known repos are present in creation-date order, and diff against a
stale canned inventory to prove new-repo + changed-description
detection. Use --no-live to skip part 2.

Run: python3 tests/smoke_test.py [--no-live]"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import org_inventory  # noqa: E402
from org_inventory import (  # noqa: E402
    diff_inventories, fetch_repos, render_queue, sort_repos, trim_repo)

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print("%s %s%s" % ("PASS:" if cond else "FAIL:", name,
                       (" — " + detail) if detail and not cond else ""))


CANNED = [
    {"name": "beta", "full_name": "acct/beta", "description": "old words",
     "private": False, "created_at": "2026-02-01T00:00:00Z",
     "pushed_at": "2026-11-01T00:00:00Z", "size": 42, "language": "Python",
     "topics": ["b", "a"], "default_branch": "main",
     "open_issues_count": 2, "html_url": "https://github.com/acct/beta"},
    {"name": "alpha", "full_name": "acct/alpha", "description": None,
     "private": True, "created_at": "2026-01-01T00:00:00Z",
     "pushed_at": "2026-10-01T00:00:00Z", "size": 7, "language": None,
     "topics": [], "default_branch": "main",
     "open_issues_count": 0, "html_url": "https://github.com/acct/alpha"},
]


def main():
    no_live = "--no-live" in sys.argv

    # --- Part 1: canned -------------------------------------------------
    trimmed = [trim_repo(e) for e in CANNED]
    check("trim keeps the queue fields, null description -> ''",
          trimmed[0]["name"] == "beta"
          and trimmed[0]["topics"] == ["a", "b"]
          and trimmed[1]["description"] == ""
          and trimmed[1]["private"] is True,
          str(trimmed))
    ordered = sort_repos(trimmed)
    check("oldest-first sort by created_at",
          [r["name"] for r in ordered] == ["alpha", "beta"])
    newest = sort_repos(trimmed, newest_first=True)
    check("newest-first sort reverses",
          [r["name"] for r in newest] == ["beta", "alpha"])
    queue = render_queue(ordered, "acct", token_used=True)
    check("queue renders one line per repo with state + private flag",
          "1. alpha (2026-01-01, private) — PENDING" in queue
          and "2. beta (2026-02-01) — PENDING — old words" in queue,
          queue)
    queue_no_token = render_queue(ordered, "acct", token_used=False)
    check("queue warns when listed without a token",
          "private repos are NOT in this list" in queue_no_token)
    old = [trim_repo(e) for e in CANNED]
    new = [dict(r) for r in old]
    new[0]["description"] = "new words"       # beta changed
    new[1]["pushed_at"] = "2026-11-12T00:00:00Z"  # alpha pushed
    new.append({"name": "gamma", "full_name": "acct/gamma",
                "description": "", "private": False,
                "created_at": "2026-03-01T00:00:00Z",
                "pushed_at": "2026-03-01T00:00:00Z", "size_kb": 1,
                "language": None, "topics": [], "default_branch": "main",
                "open_issues": 0,
                "html_url": "https://github.com/acct/gamma"})
    added, removed, changed = diff_inventories(old, new)
    check("diff finds the new repo",
          added == ["gamma"], str(added))
    check("diff finds no removals", removed == [], str(removed))
    changed_names = sorted(n for n, _ in changed)
    check("diff finds both changed repos",
          changed_names == ["alpha", "beta"], str(changed))
    beta_diffs = dict(changed)["beta"]
    check("diff shows the old -> new description",
          beta_diffs.get("description") == ("old words", "new words"),
          str(beta_diffs))

    # --- Part 2: live ---------------------------------------------------
    if no_live:
        print("SKIP: live checks (--no-live)")
    else:
        try:
            repos, detected = fetch_repos("BROKE-N-BORED")
        except Exception as exc:  # network failure is a test failure
            check("live fetch of BROKE-N-BORED succeeds", False, str(exc))
            repos, detected = [], None
        if repos:
            check("auto-detect finds a user account, not an org",
                  detected == "user", str(detected))
            names = [r["name"] for r in repos]
            check("live list has the known public repos",
                  "DUO" in names and "BNB-SKILLS" in names
                  and "CODE-FORGE" in names and len(repos) >= 20,
                  "%d repos: %s" % (len(repos), ", ".join(names[:8])))
            ordered = sort_repos(repos)
            dates = [r["created_at"] for r in ordered]
            check("live list sorts oldest first by created_at",
                  dates == sorted(dates)
                  and ordered[0]["name"] == "ChatBridgev1.0",
                  "first=%s" % (ordered[0]["name"] if ordered else None))
            check("live list marks no repo private without a token",
                  not any(r["private"] for r in repos)
                  or bool(os.environ.get("GITHUB_TOKEN")))
            # Diff the live list against a stale canned inventory:
            # DUO + BNB-SKILLS must show as new, and a tampered
            # description must show as changed.
            stale = [dict(r) for r in repos
                     if r["name"] not in ("DUO", "BNB-SKILLS")]
            for r in stale:
                if r["name"] == "CODE-FORGE":
                    r["description"] = "deliberately stale words"
            added, removed, changed = diff_inventories(stale, repos)
            check("live diff finds the held-back repos as new",
                  added == ["BNB-SKILLS", "DUO"], str(added))
            check("live diff finds the tampered description",
                  dict(changed).get("CODE-FORGE", {}).get(
                      "description", (None, None))[0]
                  == "deliberately stale words",
                  str(changed))
            # End-to-end CLI: JSON + queue files in a temp dir.
            # The CLI writes the files only on success (code 0); a
            # failed fetch returns nonzero with no files, so read
            # them only when code is 0 — otherwise this is a clean
            # FAIL, not a FileNotFoundError crash.
            cli_ok = False
            cli_detail = ""
            with tempfile.TemporaryDirectory() as tmp:
                json_path = os.path.join(tmp, "inv.json")
                queue_path = os.path.join(tmp, "queue.md")
                code = org_inventory.main([
                    "BROKE-N-BORED", "--json", json_path,
                    "--queue", queue_path])
                if code == 0:
                    with open(json_path, encoding="utf-8") as fh:
                        saved = json.load(fh)
                    with open(queue_path, encoding="utf-8") as fh:
                        queue_text = fh.read()
                    cli_ok = (len(saved["repos"]) == len(repos)
                              and "1. ChatBridgev1.0" in queue_text)
                else:
                    cli_detail = "code=%r" % code
            check("CLI writes inventory JSON + queue file",
                  cli_ok, cli_detail)
        try:
            fetch_repos("this-account-does-not-exist-zzz-123")
            check("unknown account is an error, not an empty list",
                  False, "fetch succeeded for a fake account")
        except Exception as exc:
            check("unknown account is an error, not an empty list",
                  "no GitHub user or org" in str(exc), str(exc))

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
