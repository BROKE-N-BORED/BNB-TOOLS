# org-repo-inventory

List a GitHub account's repos live and write an audit queue file.
Pairs with BNB SKILLS **org-repo-audit-queue** and complements BNB
TOOLS **repo-identity-check** (T10, one repo at a time) — this tool
lists the whole account.

## What it does

- Fetches the live repo list for a GitHub user or org (auto-detect:
  tries the org endpoint first, falls back to the user endpoint on
  404 — BROKE-N-BORED is a user account, not an org), with
  pagination.
- Sorts by creation date, oldest first by default (`--newest-first`
  reverses it), and writes:
  - a JSON inventory (`--json`), one trimmed record per repo
    (name, description, private, created/pushed dates, size,
    language, topics, default branch, open issues, URL);
  - a markdown queue file (`--queue`), one repo per line with a
    state column the audit cycle updates.
- Diffs a fresh listing against a saved inventory (`--diff`):
  reports new repos, removed repos, and repos whose description,
  topics, visibility, or last-push date changed — because metadata
  changes during the day and an older listing goes stale.

## Usage

```bash
python3 org_inventory.py BROKE-N-BORED
python3 org_inventory.py BROKE-N-BORED --json inventory.json --queue queue.md
python3 org_inventory.py BROKE-N-BORED --diff inventory-old.json
python3 org_inventory.py some-org --type org --newest-first
```

Exit code 0 = the check completed. Exit code 1 = could not check
(network failure, rate limit, unknown account) — reported as "could
not check", never as an empty repo list.

## Auth / rate limits

No auth needed for public repos. A token via the `GITHUB_TOKEN`
environment variable only (never a CLI flag, so it cannot leak into
shell history or `ps` output) lists private repos too and raises the
rate limit from 60 to 5,000 requests/hour. Without a token, private
repos are invisible — the output says so plainly instead of claiming
the account has no private repos.

## Smoke test

```bash
python3 tests/smoke_test.py [--no-live]
```

Part 1 (no network): canned-response parsing, sorting, queue
rendering, diff detection. Part 2 (live): lists BROKE-N-BORED,
asserts the known repos are present in creation-date order, and
diffs against a stale inventory. `--no-live` skips part 2.

## Source

Built from the repo-audit thread's live-listing workflow
(b074e650, 2026-11-12): the account went from 17 to 27 live repos
in one day, and two repo descriptions changed between the morning
listing and the evening audits.

## Requirements

Python 3, standard library only. Network access to `api.github.com`
for the live listing.
