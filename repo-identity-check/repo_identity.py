#!/usr/bin/env python3
"""T10 — repo-identity-check (pairs with BNB SKILLS S20).

Check a GitHub repo's identity live via the public GitHub REST API, no auth
required:

  * does the repo exist?
  * public or private? (private repos are only visible with a token)
  * empty or does it have content?
  * description + first lines of README, if present
  * heuristic keyword-overlap verdict vs a user-supplied description

Auth: optional, via the GITHUB_TOKEN environment variable only — never a CLI
flag (tokens in argv show up in shell history and process listings). Without a
token the unauthenticated rate limit applies: 60 requests/hour per IP
(GitHub docs). With a token: 5,000 requests/hour.

The get_file_contents trap: some GitHub clients report ok:true with
isError:true for a missing file. This tool never does that — a 404 from the
API is reported as MISSING, plainly, in every code path. A network failure is
reported as "could not check", never as "does not exist".

Usage:
    repo_identity.py owner/repo
    repo_identity.py owner/repo --description "a stem separation trainer"
    repo_identity.py owner/repo --json
    repo_identity.py --name stella --owner BROKE-N-BORED

Exit codes: 0 = check completed (regardless of exists/not-exists),
1 = could not check (network / rate limit / bad input).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "bnb-tools-repo-identity-check/1.0"

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "is", "it",
    "with", "that", "this", "by", "as", "at", "from", "into", "my", "app",
}


class CouldNotCheck(Exception):
    pass


def api_get(path):
    """GET a GitHub API path. Returns (status, parsed_json_or_None).

    A 404 returns (404, None) — callers must treat that as MISSING, never ok.
    Network errors and rate limits raise CouldNotCheck.
    """
    url = API + path
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, None
        if e.code == 403:
            body = e.read().decode("utf-8", "replace")
            if "rate limit" in body.lower():
                raise CouldNotCheck(
                    "GitHub API rate limit reached (unauthenticated: 60/hr). "
                    "Wait, or set GITHUB_TOKEN for 5,000/hr.")
            raise CouldNotCheck("GitHub API returned 403: %s" % body[:200])
        raise CouldNotCheck("GitHub API returned HTTP %d" % e.code)
    except urllib.error.URLError as e:
        raise CouldNotCheck("network failure: %s" % e.reason)
    except (TimeoutError, OSError) as e:
        raise CouldNotCheck("network failure: %s" % e)


def check_repo(full_name):
    """Return a dict describing the repo. Raises CouldNotCheck on failure."""
    if "/" not in full_name:
        raise CouldNotCheck(
            "repo must be given as owner/name, got %r" % full_name)
    status, data = api_get("/repos/" + full_name)
    result = {"repo": full_name, "exists": status != 404}
    if status == 404:
        result["note"] = ("No public repo at this name (or it is private and "
                          "no token was supplied).")
        return result
    result["private"] = bool(data.get("private"))
    result["description"] = data.get("description")
    result["url"] = data.get("html_url")
    result["default_branch"] = data.get("default_branch")
    result["size_kb"] = data.get("size")
    # Empty? The repo contents endpoint 404s on an empty repo, and the API
    # also reports size 0. Check contents directly — the honest signal.
    cstatus, _cdata = api_get("/repos/%s/contents/" % full_name)
    if cstatus == 404:
        result["empty"] = True
        result["empty_evidence"] = "contents endpoint returned 404"
    else:
        result["empty"] = False
        result["empty_evidence"] = "contents endpoint returned %d" % cstatus
    # README first lines, if present. 404 here means NO README — never "ok".
    rstatus, rdata = api_get("/repos/%s/readme" % full_name)
    if rstatus == 404 or not rdata:
        result["readme"] = None
        result["readme_note"] = "no README found (404)"
    else:
        import base64
        try:
            text = base64.b64decode(rdata.get("content", "")).decode(
                "utf-8", "replace")
        except Exception:
            text = ""
        lines = [ln for ln in text.splitlines() if ln.strip()][:5]
        result["readme"] = {
            "name": rdata.get("name"),
            "first_lines": lines,
        }
    return result


def keywords(text):
    words = re.findall(r"[a-z0-9][a-z0-9\-]*", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def match_verdict(result, description):
    """Heuristic keyword overlap. Labelled as a heuristic everywhere it is
    shown — never a confident match claim. Returns (score, shared, verdict)."""
    hay = " ".join([
        result.get("description") or "",
        result.get("repo", "").replace("/", " ").replace("-", " "),
        " ".join((result.get("readme") or {}).get("first_lines", [])),
    ])
    want = keywords(description)
    have = keywords(hay)
    shared = sorted(want & have)
    score = (len(shared) / len(want)) if want else 0.0
    if score >= 0.5 and len(shared) >= 2:
        verdict = ("HEURISTIC: looks like a plausible match "
                   "(shared keywords: %s) — confirm with the owner."
                   % ", ".join(shared))
    elif shared:
        verdict = ("HEURISTIC: weak overlap (shared: %s) — "
                   "not enough to call it a match." % ", ".join(shared))
    else:
        verdict = "HEURISTIC: no keyword overlap with the description."
    return score, shared, verdict


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check a GitHub repo's existence, emptiness and "
                    "description (public API, no auth needed).")
    ap.add_argument("repo", nargs="?",
                    help="repo as owner/name, e.g. torvalds/linux")
    ap.add_argument("--owner", help="owner, used with --name")
    ap.add_argument("--name", help="repo name, used with --owner")
    ap.add_argument("--description",
                    help="user-supplied description to compare against "
                         "(heuristic keyword overlap only)")
    ap.add_argument("--json", action="store_true",
                    help="print the result as JSON")
    args = ap.parse_args(argv)

    full = args.repo
    if args.owner or args.name:
        if not (args.owner and args.name):
            ap.error("--owner and --name must be given together")
        full = "%s/%s" % (args.owner, args.name)
    if not full:
        ap.error("give a repo as owner/name, or --owner + --name")

    try:
        result = check_repo(full)
    except CouldNotCheck as e:
        print("COULD NOT CHECK: %s" % e, file=sys.stderr)
        return 1

    verdict = None
    if args.description and result["exists"]:
        _score, _shared, verdict = match_verdict(result, args.description)
        result["description_match"] = {
            "score": round(_score, 2),
            "shared_keywords": _shared,
            "verdict": verdict,
            "method": "keyword overlap — heuristic, not a confident match",
        }

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("repo:        %s" % result["repo"])
    print("exists:      %s" % ("YES" if result["exists"] else "NO"))
    if not result["exists"]:
        print("note:        %s" % result["note"])
        return 0
    print("visibility:  %s" % ("private" if result["private"] else "public"))
    print("url:         %s" % result["url"])
    print("empty:       %s (%s)"
          % ("YES" if result["empty"] else "NO", result["empty_evidence"]))
    print("description: %s" % (result["description"] or "(none)"))
    print("branch:      %s" % result["default_branch"])
    if result["readme"]:
        print("readme:      %s" % result["readme"]["name"])
        for ln in result["readme"]["first_lines"]:
            print("             | %s" % ln)
    else:
        print("readme:      %s" % result["readme_note"])
    if verdict:
        print("match:       %s" % verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
