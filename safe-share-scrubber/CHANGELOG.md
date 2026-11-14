# Changelog

## v0.2.0 - 2026-11-14

Structural breakup only. Behavior is unchanged: the same eleven
secret shapes, the same markers, the same reports, the same
window.

- The window is now a thin viewer. It does no scrubbing or
  verifying itself: it runs the terminal commands and shows their
  results, reading the report file the scrub command wrote. The
  window and the terminal always agree.
- New `verify` command: scan files without writing anything.
  Exit 0 when clean, 1 when a secret is found, 2 when a file
  could not be scanned. The window has a Verify button and menu
  item for it.
- New one-job commands: `safe-share-scrub` (scrub only) and
  `safe-share-verify` (verify only). The full command
  `safe-share-scrubber` still carries every subcommand.
- `scrub` and `verify` both take `--json` to print the results
  as JSON instead of the human report.
- Cancel now stops the running command outright instead of
  waiting for it to finish.

## v0.1.0 - 2026-11-14

First release.

- Find secrets in a file before you share it: AWS keys, JWTs,
  private keys, GitHub, Slack, and Google tokens, bearer tokens,
  passwords and secrets in assignment form, and secrets buried in
  tracebacks and URLs. Each one is replaced with a labeled marker
  like [REDACTED AWS KEY], and the report lists what was found by
  kind and line number, never showing the secret itself.
- Drop in one file or several at once. Each gets a safe copy next
  to it, with ".safe" in the name, plus a short report file.
  Originals are never changed or overwritten. Binary files are
  skipped and the report says so.
- The honest caveat, stated in the app and the README: redaction
  is pattern-based, so the app can only catch the kinds of secrets
  it knows how to look for.
- One window with a menu bar, How to Use window, status bar,
  single instance, and remembered window size.
- Command line: scrub, debug-report.
- Debug log layer: rotating log, recent-actions record, scrubbed
  debug report on demand and on crash.
- Double-click GUI installer with a private tools folder, app
  menu entry, desktop icon, and uninstaller.
