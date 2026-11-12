# T10 — repo-identity-check

GitHub existence / empty / description check for a repo name, via the public
GitHub API. Pairs with BNB SKILLS **S20** (repo-identity check).

## What it does

Given `owner/repo`, reports live from GitHub:

- **exists** — yes/no
- **visibility** — public/private (private repos only show with a token)
- **empty** — yes/no, judged from the repo contents endpoint
- **description** + first lines of the README, if present
- **match verdict** vs a user-supplied description — keyword overlap, clearly
  labelled as a heuristic, never a confident match claim

## The trap it avoids

Some GitHub clients return `ok: true` with `isError: true` for a missing file.
This tool never does that: a 404 from the API is reported as **MISSING** in
every code path (repo, contents, README). A network failure is reported as
**"could not check"**, never as "does not exist".

## Usage

```bash
python3 repo_identity.py torvalds/linux
python3 repo_identity.py BROKE-N-BORED/StemLab --description "a stem separation trainer"
python3 repo_identity.py --owner BROKE-N-BORED --name STELLA --json
```

Exit code 0 = the check completed (even if the repo does not exist).
Exit code 1 = could not check (network failure, rate limit, bad input).

## Auth / rate limits

No auth needed. Optional token via the `GITHUB_TOKEN` environment variable
only — never a CLI flag, so it can't leak into shell history or `ps` output.

- Unauthenticated: **60 requests/hour per IP** (GitHub's public limit).
- With a token: 5,000 requests/hour.

Each check costs 3 API calls (repo, contents, README).

## Requirements

Python 3, standard library only. Network access to `api.github.com`.
