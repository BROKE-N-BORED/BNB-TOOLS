# T4 — name-check

Pairs with skill **S7** (name-availability check — GitHub exact-name + web).

Batch name-availability check. Born from a failure: a repo was created for an unchecked name that was already taken. Durable rule: check before presenting ANY name.

## What it does

For each candidate name it runs two checks with different authority:

- **GitHub exact-name search — AUTHORITATIVE.** Queries the public GitHub search API (`search/repositories`, `in:name`) and reports repos whose name matches exactly (case-insensitive). No auth by default; unauthenticated search is limited to 10 requests/minute, so the tool sleeps 6s between names (see `--delay`) and backs off on 403/429. An optional token via the `GITHUB_TOKEN` **environment variable** raises the limit — never pass a token on the command line.
- **Web check — INDICATIVE only.** Tries an HTTPS GET on `<name>.com` and a DuckDuckGo HTML search fetch. A live site or a same-name result is evidence the name is taken; an empty result is weak evidence it is free — search coverage is not exhaustive, and fetching search-results pages is fragile by nature. Web results are labelled indicative, never authoritative.

**Offline-degraded by design:** any network failure yields verdict `could not check`, never `clean`. A name is `clean` only when the GitHub exact-name check ran and found no exact-name repo AND the web checks ran without finding a same-name product/site.

## Requirements

Python 3.8+, stdlib only. Network access for the checks themselves.

## Usage

```bash
# Check names on the command line
python3 namecheck.py WinLinx WinLink EveryMouse

# Check names from a file (one per line)
python3 namecheck.py --file candidates.txt

# GitHub only, machine-readable output
GITHUB_TOKEN=ghp_... python3 namecheck.py --skip-web --json --file candidates.txt
```

Exit codes: 0 = every name got a definite verdict; 2 = at least one name could not be checked.

## Smoke test

```bash
bash smoke_test.sh
```

Runs `--help` plus a check of a certainly-taken name (`linux`) and a random gibberish name. Network availability in the sandbox decides whether the verdicts are definite or "could not check" — the smoke test reports what actually happened.
