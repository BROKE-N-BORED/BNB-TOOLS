# Changelog

## v0.1.0 - 2026-11-18

First release.

- `check`: reads a built zip, lists the stored mode of every
  `.sh` and `.desktop` entry, fails (exit 1) if any is not
  stored 0o100755, passes (exit 0) otherwise. A bare 0o755
  with no file-type bits fails (GUI extractors drop its exec
  bit), and so does an entry with no stored Unix mode at
  all. Exit 2 when the check cannot run. Errors are plain
  words naming the missing thing, never a traceback.
- `fix`: rebuilds the zip with correct modes (0o100755 for
  `.sh` and `.desktop`, 0o40755 for directories, 0o100644
  for plain files with no stored Unix mode) and reports
  every change. Plain files that already carry a Unix mode
  are left exactly as stored. Contents, order, compression,
  dates, and comments are preserved. Default output is
  `<name>-modes-fixed.zip`; overwriting the input needs an
  explicit `--in-place`, which is atomic and leaves the
  original untouched on failure.
- `--json` on check for machine-readable output (modes as
  octal strings, `null` for no stored mode).
- `--debug-report PATH` on check and fix, plus a
  `debug-report` subcommand: the verbatim T21 debug log
  layer.
- Standard library only. No installer, no GUI: a script
  tool in the T28/T33/T34 family.
- The OST v22 incident is the worked example in the README:
  `installer.desktop` shipped non-executable in Release
  v22, double-clicking opened a text editor, and the fixed
  asset had to be re-uploaded.
- 48 tests, no network: fixture zips with exact stored
  modes cover the check, the CLI, the fix, the debug
  report, running without `debug_log.py`, and the built
  zip's own stored modes.
