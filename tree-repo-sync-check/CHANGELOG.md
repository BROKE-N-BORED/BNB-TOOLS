# Changelog

## v0.1.0 - 2026-11-15

First release.

- Compare a local directory against a public GitHub repo
  branch, file by file, using git blob SHAs (computed
  in-process, identical to `git hash-object`, no git binary
  needed). One API call fetches the remote tree.
- Three drift buckets: differing, missing on remote (extra
  local files), missing locally (only on remote). Exit 0
  clean, 1 differences found, 2 could not check. Errors are
  plain words naming the missing thing, never a traceback.
- Public repos only, no auth of any kind: no token, no login,
  no Authorization header. A private repo answers 404 or 403
  and is reported as "could not check".
- Rate limits stop cleanly: exactly one request, no retry,
  the reset time named in the error.
- `--json` for machine-readable output in all three outcomes
  (clean, differences, error). `--branch` (default main),
  `--timeout` (default 30s).
- `--debug-report PATH` on a check, plus a `debug-report`
  subcommand: the verbatim T21 debug log layer, wired with
  the GitHub API as its one service check.
- The BNB-PLUGINS case is the worked example in the README:
  the 2026-11-14 audit found the repo shipping broken code
  while the tree had the fixes in `github/plugin.py` and
  `huggingface/plugin.py`, with nothing re-checking it. This
  tool is that check.
- 48 tests, no live network: a local fake GitHub server
  (the T30 pattern) covers the drift buckets, JSON output,
  branch handling, 404/403/500/truncated/bad-JSON/no-tree
  failures, rate limits, no-network, and the zip modes.
