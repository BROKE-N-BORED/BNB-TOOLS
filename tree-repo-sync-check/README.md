# T33 - tree-repo-sync-check

Pairs with skill **S1** (ship pipeline - verify, push, Release,
hash-match).

A small chainable checker: does a public GitHub repo ship what
is in the local tree? It compares a local directory against a
remote branch file by file, using git blob SHAs, and reports
three kinds of drift:

- **differing**: the file exists in both, with different content
- **missing on remote**: the file is in the local tree but not
  on remote (extra local files: fixes or files never pushed)
- **missing locally**: the file is on remote but not in the
  local tree

Exit 0 means clean, 1 means differences found, 2 means the
check could not run (no network, repo or branch not found,
rate limited, bad input). Errors are plain words naming the
missing thing, never a traceback.

## Why it exists: the BNB-PLUGINS case

The BNB-PLUGINS audit of Sat 2026-11-14 01:19 (audit thread
b074e650) found, in its own words, "the repo ships the broken
code while the tree has the fixes". The local tree had fixed
two live-proven defects, the repo never re-synced, and nothing
in the repo re-checks it: no checker, no CI, no re-sync rule.
The audit did the comparison by hand. This tool is that check,
automated, so the next drift is caught by running one command
instead of by another audit.

The two defects, both proven live in the earlier audit:

1. `huggingface/plugin.py`: `hf_model_info` failed with HTTP
   400 on every call, because the repo path was quoted with
   `safe=''`, encoding the owner/name slash to `%2F`.
2. `github/plugin.py` and `huggingface/plugin.py`: a junk
   `limit` crashed both search handlers with an uncaught
   `ValueError`, because the `int(...)` conversion sat outside
   the `try` block.

Run against the plugins tree on the morning of that audit,
this tool would have printed:

```text
$ python3 tree_repo_sync_check.py ~/workspace/bnb-plugins BROKE-N-BORED/BNB-PLUGINS
Checking /home/hatch/workspace/bnb-plugins against BROKE-N-BORED/BNB-PLUGINS (main)...
DIFFERENCES FOUND: 2 differing, 0 missing on remote, 0 missing locally.
Differing (2):
  github/plugin.py
  huggingface/plugin.py
```

Exit 1. Both files named, no digging. After the re-sync, the
same command prints `OK: local tree matches the remote tree`
and exits 0.

## Requirements

Python 3.8+, standard library only. No git binary needed: the
local blob SHAs are computed in-process (SHA-1 of the git blob
header plus the bytes, identical to `git hash-object`; the test
suite cross-checks the formula against real `git hash-object`
when git is installed). No account, no token, no login. This is
a CLI script tool, not a GUI app.

Public repos only. This tool sends no auth of any kind, so a
private repo answers 404 or 403 to an unauthenticated request
and this tool reports that as "could not check" rather than
guessing. If you need private repos, that is a different tool
with a credential flow, not a flag on this one.

## Usage

```bash
python3 tree_repo_sync_check.py <local-dir> <owner/repo>
python3 tree_repo_sync_check.py ~/workspace/bnb-plugins BROKE-N-BORED/BNB-PLUGINS --branch main
python3 tree_repo_sync_check.py <local-dir> <owner/repo> --json
python3 tree_repo_sync_check.py debug-report [--out PATH]
python3 tree_repo_sync_check.py --help
```

| Option | Default | What it does |
| --- | --- | --- |
| `--branch BRANCH` | `main` | Remote branch to compare against |
| `--json` | off | Print the result as JSON, including errors (which otherwise go to stderr) |
| `--timeout SECONDS` | 30 | Seconds to wait for the GitHub reply |
| `--debug-report PATH` | none | Also write a debug report to PATH (T21 debug log layer; the path is printed on stderr so `--json` output stays clean) |
| `--api-base URL` | `https://api.github.com` | GitHub API base URL, for tests only (or `TREE_SYNC_API_BASE` when set) |

A clean check prints one line and exits 0:

```text
Checking /home/hatch/workspace/bnb-plugins against BROKE-N-BORED/BNB-PLUGINS (main)...
OK: local tree matches the remote tree (29 files).
```

A check with drift prints every differing file by path, grouped
into the three buckets, and exits 1. A check that cannot run
prints one plain-words error to stderr and exits 2, for example:

```text
error: repo or branch not found on GitHub: BROKE-N-BORED/BNB-PLUGINS (branch main). Check the owner, repo name, and branch. Private repos also answer this way: this tool only checks public repos.
```

## What it compares

- One GitHub API call fetches the remote tree:
  `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1`.
  Each remote blob SHA is compared against the local blob SHA
  for the same path.
- The local side is the tree on disk, not the git index. An
  untracked or ignored file shows up as missing on remote.
  That is by design: the question is "does the repo ship what
  is on this disk", not "is the git index clean".
- The `.git` directory is skipped. A symlink is hashed by its
  target path, the way git stores it. Binary files compare by
  bytes, like any other file.

What it does not compare:

- File modes. A blob SHA does not cover the exec bit, so a
  file that only changed mode reads as clean.
- Submodules. Remote entries of type `commit` (submodules)
  and `tree` (directories) are ignored; only blobs compare.
- Repos too large for one tree listing. When GitHub truncates
  the remote tree, the tool stops with exit 2 and says so
  plainly, rather than reporting a partial comparison as a
  result.

## JSON output

For chaining into other tools (local CI, audit scripts):

```json
{
  "branch": "main",
  "differing": ["github/plugin.py", "huggingface/plugin.py"],
  "local_dir": "/home/hatch/workspace/bnb-plugins",
  "local_files": 29,
  "missing_locally": [],
  "missing_on_remote": [],
  "remote_files": 29,
  "repo": "BROKE-N-BORED/BNB-PLUGINS",
  "status": "differences"
}
```

On an error, `--json` prints `{"status": "error", "error": ...,
"rate_limit_reset": ...}` on stdout (null unless rate limited)
and exits 2, so a caller can parse stdout in every case.

## Rate limits

The tool makes exactly one API request. If GitHub answers that
the rate limit is reached, the tool stops cleanly, names the
reset time, and never retries:

```text
error: GitHub API rate limit reached. No retry was made. The limit resets at 2026-11-15T13:00:00Z. Try again after that time.
```

Unauthenticated GitHub API calls share a low hourly budget, so
do not run this in a tight loop. One check per repo per ship is
the intended pace; the suite proves the single-request behavior
against a fake server.

## Debug report

`--debug-report PATH` on a check, or the `debug-report`
subcommand on its own, writes a T21 debug log report: app and
version, the GitHub API status, the recent actions, and any
errors. The log layer is the verbatim `debug_log.py` (SHA-256
`d304c17e...`), kept next to the script; its log dir is a temp
dir, so no `logs/` directory is left behind. The tool has no
credentials, so there is nothing secret to scrub, and the layer
scrubs secret-shaped values anyway.

## Smoke test

```bash
bash run_tests.sh
```

48 tests, no live network: every network test runs against a
local fake GitHub server (the T30 pattern). Covers help and
version, bad input, all three drift buckets including the
BNB-PLUGINS two-file case, JSON output in all three outcomes,
branch handling, 404/403/500/truncated/bad-JSON/no-tree
failures, rate limits (reset time named, exactly one request,
no retry), no-network, no Authorization header, `.git`
skipping, symlinks, submodule entries, binary files, the blob
SHA against real `git hash-object`, the debug log wiring, and
the release zip modes. The suite never touches the live
network or the live plugins repo; the coordinator runs a live
check at ship time.

## What it does not do

- It does not sync anything. It reports drift; the re-sync
  (copy, commit, push) stays manual, under S1.
- It does not check private repos. See above.
- It does not watch for changes or run on a schedule. It runs
  when you run it, before a push or after an audit.
- It does not verify the pushed repo beyond the tree listing:
  S1's read-back step still applies after the push.
- It does not compare file modes or submodules. See above.
