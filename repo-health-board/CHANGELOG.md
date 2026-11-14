# Changelog

## v0.1.0 - 2026-11-14

First release. The board is three small chainable pieces plus a
thin viewer, not one big package.

- board-fetch: checks an org on GitHub and writes repos.json.
  Progress lines as it goes, plain exit codes (0 ok, 1 partial,
  2 could not run). No sign-in, no token, ever.
- board-flag: reads repos.json, applies the health rules, and
  writes flagged.json and board.txt.
- The viewer: a thin window that only displays flagged.json.
  Sortable table (name, last commit date, flag count, and the
  rest), click a repo name to open it on GitHub, Refresh runs
  fetch and flag in the background with Cancel, and the 60 an
  hour GitHub limit is explained in plain words with the time
  to try again.
- board-cli: the one-command full run (refresh, show, export,
  debug-report).
- The health rules: placeholder, missing README / LICENSE /
  .gitignore / SECURITY.md, missing description, missing
  topics, stale (no commit in 90 days). Suite status is
  presence only: has CI, no CI file, or unknown.
- The cache: repo details are cached with ETags, so a second
  refresh reuses what has not changed and uses fewer of the 60
  hourly checks.
- Packaging: double-click GUI installer (private tools folder,
  python3-venv self-heal, success dialog, error dialog with the
  log path), app menu entry and desktop icon, board-cli,
  board-fetch, and board-flag on the command line, uninstaller.
- Debug log layer in the app and the CLI: File, Generate debug
  report writes a report you can send to
  broke.n.bored.studio@gmail.com.
