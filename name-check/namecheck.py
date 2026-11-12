#!/usr/bin/env python3
"""T4 name-check — batch name-availability check (GitHub exact-name + web).

Pairs with skill S7. Born from a failure: a repo was created for an
unchecked name that was already taken. Durable rule: check before
presenting ANY name.

Two halves, different authority:
  * GitHub exact-name search — AUTHORITATIVE. Uses the public GitHub
    search API (https://api.github.com/search/repositories) with NO auth
    by default. Unauthenticated rate limit is 10 search requests per
    minute (and 60 core requests/hour); the tool sleeps between names
    and backs off on 403/429. An optional token via the GITHUB_TOKEN
    environment variable raises the limit — NEVER pass a token on the
    command line (it lands in shell history / process lists).
  * Web check — INDICATIVE only. Tries an HTTPS GET on <name>.com and
    a DuckDuckGo HTML search fetch. A live site or a same-name result
    is evidence the name is taken; an empty result is weak evidence
    the name is free (search coverage is not exhaustive). Fetching a
    search-results page is fragile by nature — results are labelled
    indicative, never authoritative.

Offline-degraded by design: any network failure yields verdict
"could not check", NEVER "clean". A name is "clean" only when the
GitHub exact-name check ran and found no exact-name repo AND the web
checks ran without finding a same-name product/site.

Stdlib only. Python 3.8+.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API = "https://api.github.com/search/repositories"
DDG_HTML = "https://html.duckduckgo.com/html/"
USER_AGENT = "bnb-tools-name-check/1.0 (+https://github.com/BROKE-N-BORED/BNB-TOOLS)"
REQUEST_TIMEOUT = 20


def slugify(name):
    """Domain-safe form of a candidate name for the <name>.com probe."""
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return slug


def fetch(url, headers=None, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def github_exact_search(name, token=None):
    """Return (checked_ok, exact_repos, evidence, error).

    exact_repos: list of full repo names whose repo name matches exactly
    (case-insensitive). checked_ok False means the check could not run.
    """
    query = urllib.parse.quote(f"{name} in:name")
    url = f"{GITHUB_API}?q={query}&per_page=10"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, body = fetch(url, headers)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            retry = e.headers.get("Retry-After")
            return (False, [], [],
                    f"GitHub rate-limited (HTTP {e.code})"
                    + (f", retry after {retry}s" if retry else "")
                    + " — set GITHUB_TOKEN or wait a minute")
        return (False, [], [], f"GitHub API HTTP {e.code}")
    except Exception as e:  # network failure, DNS, timeout...
        return (False, [], [], f"GitHub check failed: {e}")
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return (False, [], [], "GitHub returned unparsable JSON")
    exact = []
    for item in data.get("items", []):
        repo_name = item.get("name", "")
        if repo_name.lower() == name.lower():
            exact.append(item.get("full_name", repo_name))
    total = data.get("total_count", 0)
    evidence = [f"GitHub search 'in:name' returned {total} repo(s)"]
    if exact:
        evidence.append(f"exact-name repos: {', '.join(exact)}")
    return (True, exact, evidence, None)


def web_check(name):
    """Return (checked_ok, hits, evidence, error). Indicative only."""
    hits = []
    evidence = []
    checked_any = False
    slug = slugify(name)
    # Probe 1: <name>.com
    if slug:
        url = f"https://{slug}.com"
        try:
            status, _ = fetch(url)
            checked_any = True
            hits.append(f"{slug}.com responds (HTTP {status})")
            evidence.append(f"{url} is live (HTTP {status})")
        except urllib.error.HTTPError as e:
            checked_any = True
            # Any real HTTP response means the domain is live.
            hits.append(f"{slug}.com responds (HTTP {e.code})")
            evidence.append(f"{url} is live (HTTP {e.code})")
        except Exception as e:
            evidence.append(f"{url} unreachable ({e}) — no site found")
            checked_any = True  # a DNS/NXDOMAIN failure IS an answer here
    # Probe 2: DuckDuckGo HTML search
    try:
        q = urllib.parse.quote(name)
        status, body = fetch(f"{DDG_HTML}?q={q}")
        checked_any = True
        text = body.decode("utf-8", "replace")
        # Count result links whose visible text mentions the name.
        results = re.findall(r'class="result__a"[^>]*>(.*?)</a>', text,
                             re.IGNORECASE | re.DOTALL)
        if not results:
            # Zero parseable results even for a common name means the
            # page came back bot-blocked or re-laid-out, not that the
            # name is free. Say so; do not treat it as clean evidence.
            evidence.append("DuckDuckGo returned no parseable results "
                            "(page may be bot-blocked or re-laid-out) — "
                            "DDG probe inconclusive")
        same = [re.sub(r"<[^>]+>", "", r).strip() for r in results
                if name.lower() in re.sub(r"<[^>]+>", "", r).lower()]
        if same:
            hits.append(f"DuckDuckGo: {len(same)} result(s) mention "
                        f"'{name}' (e.g. {same[0][:80]!r})")
            evidence.append(f"DuckDuckGo returned {len(results)} results, "
                            f"{len(same)} mention the name")
        elif results:
            evidence.append(f"DuckDuckGo returned {len(results)} results, "
                            "none mention the name")
    except Exception as e:
        evidence.append(f"DuckDuckGo fetch failed ({e})")
    return (checked_any, hits, evidence, None)


def check_name(name, token=None, skip_web=False):
    gh_ok, exact, gh_evidence, gh_error = github_exact_search(name, token)
    web_ok, web_hits, web_evidence, _ = ([True, [], [], None] if skip_web
                                         else web_check(name))
    if skip_web:
        web_evidence = ["web check skipped (--skip-web)"]
    verdict = "clean"
    reasons = []
    if not gh_ok:
        verdict = "could not check"
        reasons.append(f"GitHub: {gh_error}")
    elif exact:
        verdict = "dead"
        reasons.append(f"GitHub exact-name repo(s): {', '.join(exact)}")
    if verdict != "could not check" and web_hits:
        verdict = "dead"
        reasons.extend(web_hits)
    if verdict == "clean":
        reasons.append("no exact-name GitHub repo; no same-name site found")
    return {
        "name": name,
        "verdict": verdict,
        "github_checked": gh_ok,
        "github_exact_repos": exact,
        "web_hits": web_hits,
        "evidence": gh_evidence + web_evidence,
        "reasons": reasons,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="namecheck.py",
        description="Batch name-availability check: GitHub exact-name "
                    "(authoritative) + web (indicative).")
    ap.add_argument("names", nargs="*",
                    help="candidate names to check")
    ap.add_argument("--file", default=None,
                    help="file with one candidate name per line")
    ap.add_argument("--skip-web", action="store_true",
                    help="GitHub check only")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    ap.add_argument("--delay", type=float, default=6.0,
                    help="seconds between GitHub calls (default 6; "
                         "unauthenticated search limit is 10/min)")
    args = ap.parse_args(argv)
    names = list(args.names)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            names += [ln.strip() for ln in f if ln.strip()]
    if not names:
        ap.error("no names given — pass names or --file")
    token = os.environ.get("GITHUB_TOKEN")
    results = []
    for i, name in enumerate(names):
        if i > 0:
            time.sleep(args.delay)
        results.append(check_name(name, token, args.skip_web))
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"\n{r['name']}: {r['verdict'].upper()}")
            for reason in r["reasons"]:
                print(f"  - {reason}")
            for ev in r["evidence"]:
                print(f"    evidence: {ev}")
        n_clean = sum(1 for r in results if r["verdict"] == "clean")
        n_dead = sum(1 for r in results if r["verdict"] == "dead")
        n_unk = sum(1 for r in results if r["verdict"] == "could not check")
        print(f"\nsummary: {n_clean} clean, {n_dead} dead, "
              f"{n_unk} could not check (of {len(results)})")
    # Exit 0 only if every name got a definite verdict; unknown = 2.
    if any(r["verdict"] == "could not check" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
