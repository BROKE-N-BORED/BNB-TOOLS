# Changelog

## v0.1.0 - 2026-11-17

First release.

- The shared updater module (`silent_update_check.py`):
  stdlib only, one droppable file, four chainable pieces.
  (1) check: silent launch check vs the GitHub Latest
  Release, one API request, no auth, public repos only.
  (2) pull-verify: ask-first pull, SHA-256 checksum/sidecar
  verification before anything installs, no blind downloads
  (no usable checksum means the pull refuses; a mismatch
  deletes the staged files). (3) install-swap: rename-based
  swap-over install that never leaves a half-installed app,
  with the previous version kept for rollback.
  (4) restart-prompt: ask-first restart through the caller's
  popup; Yes applies and re-execs, No leaves the staged
  update waiting for the next launch with no re-download.
- Partial implementations: `missing_pieces()` lists what a
  project still needs (notify-only gets pull-verify,
  install-swap, restart-prompt); each function stands alone.
- Multi-platform repos: only the matching platform's assets
  are offered (the Android Photo Transfer case); `.zip` wins
  among matches. A newer release with no asset for this
  platform reports no-release-for-platform.
- State and staging live in a sibling dir (`<app>.update`),
  so the swap never touches them; `state.json` is written
  atomically. `apply_pending_on_launch()` is the launch-time
  hook; `rollback()` restores the kept backup.
- CLI: `check` / `pull` / `install` / `apply-pending` /
  `rollback` / `restart` / `run` (the whole chain) /
  `debug-report`, plus `--help` / `--version`. Exit 0 did
  the step, 1 nothing to do, 2 could not run. Plain-words
  errors, never a traceback. Python 3.8+ guard with a
  regression test.
- Demo harness (`demo.py`): a fake local release server
  stands in for GitHub, a fake app in a temp dir stands in
  for a real project; proves each piece alone (`--pieces`)
  and the full chain with restart Yes (default) and No
  (`--answer no`, then a second launch applies with no
  re-download). No network, no real exec (a recorder stands
  in for `os.execv`).
- Debug report (`debug-report`): the T21 debug log layer,
  copied unmodified (SHA-256 pinned in the tests), imported
  lazily so the launch-check path never pays its import
  cost. Normal runs never touch it and never create a
  `logs/` dir.
- 126 tests, no live network: version comparison, platform
  matching, asset picking, checksum parsing, the check
  (including rate limit with reset named and exactly one
  request, no Authorization header), the pull (including
  mismatch, no sidecar, zip-slip), the swap (including
  failed-swap restore), the restart ask and the real exec
  path through the CLI, launch apply and rollback, the full
  chain both ways, the demo in all three modes, stdlib-only
  imports, the no-em-dash rule, and the release zip modes.
