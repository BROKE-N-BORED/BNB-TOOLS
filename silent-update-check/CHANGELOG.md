# Changelog

## v0.1.1 - 2026-11-18

README only, no code change (Delta 8). The SOLDAR rollback
lesson was checked against the code first: `rollback()`
already restores every build folder (it renames the whole
previous app directory back into place), so no code change
was needed.

- Rollback check: confirmed in the code and the tests.
  `rollback()` moves the current version aside to `failed/`
  and renames the whole backup directory back into place,
  every folder inside it; the swap likewise renames the
  whole app directory, so no per-file step can leave an app
  half-upgraded. Tests: `TestLaunchAndRollback.
  test_rollback_restores_the_backup`,
  `TestLaunchAndRollback.test_rollback_with_no_backup`,
  `TestInstallSwap.test_backup_keeps_the_old_version`,
  `TestCLI.test_rollback_cli`, and `TestInstallSwap.
  test_failed_swap_puts_the_old_version_back`.
- New section: rollback restores every build folder. The
  SOLDAR self-update drive (2026-11-17 ~22:00) left the
  engine half-upgraded and the app unable to start; the
  failure mode here is safe rollback, never a broken
  install. Known limitation recorded: an update does not
  remove files a newer version deleted (SOLDAR's updater);
  the whole-directory swap sidesteps it, since the staged
  version replaces the entire app directory.
- New section: proving the loop, fake server first, live
  GitHub after publish. Two-stage proof (Android Photo
  Transfer v0.1.1, 2026-11-18, the first live-GitHub proof:
  0.1.0 offered 0.1.1, 0.1.1 reports current); download-back
  proof after publishing (GITDATA v0.1.5: download the
  release zip back from GitHub and verify its hash, which
  also proves the updater's download path against real
  GitHub); sidecar rule (a release published without the
  `.sha256` sidecar is never offered, so the publish
  checklist must include uploading the sidecar).

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
