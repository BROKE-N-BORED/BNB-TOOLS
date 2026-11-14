# Changelog

## v0.2.0 - 2026-11-14

The engine is split into small, chainable pieces, and the window
is a thin viewer over them. The window looks and behaves the same;
what changed is underneath.

- The chain: `vision-shrink` shrinks one picture, `vision-describe`
  describes one picture as given, and the window views the result.
  Each command runs on its own; chained together they are the full
  run (`vision-shrink photo.png && vision-describe
  photo-512w.jpg`), the same thing the Describe button does.
- The GUI no longer shrinks or describes anything itself. Optimize
  runs the shrink step, Describe runs shrink then describe, the
  cache label comes from `cache-stats`, and Clear cache runs
  `cache-clear`. Everything runs in a worker thread, so the window
  never blocks; Cancel kills the running step promptly.
- Describe behavior change: `vision-describe` (and the `describe`
  subcommand) no longer shrinks first. It describes the file as
  given. Hand it the shrunken copy for the small-token look; the
  window's Describe button still saves that copy first.
- New commands on PATH after install: `vision-shrink` and
  `vision-describe`, next to `vision-image-optimizer`. Both take
  `--json` for one machine readable result object.
- New `cache-stats` subcommand (with `--json`): how many optimized
  pictures and descriptions the cache holds, and how much disk
  they take.
- The release zip is written outside the tool folder by default
  (use `--out` to pick a destination), so the folder stays all
  UTF-8 text.

## v0.1.0 - 2026-11-14

First release.

- Shrink pictures before a local vision model looks at them:
  resize to 512w / 768w / 1024w / original / custom width, JPEG
  quality picker, crop with a rubber band on the preview, JPEG or
  PNG output. Optimized copies go to an `optimized` folder next to
  the original; originals are never changed or overwritten.
- Vision token counts before and after, per picture and in total
  (1920x1080 reads 2040 tokens, 512x288 reads 144).
- Describe with the local model: a small model looks first, the
  careful model only wakes up if the small one cannot see enough.
  Runs in a worker thread with a Cancel button and a busy light.
  If Ollama is down, the window says so plainly and shrinking
  keeps working.
- Hash-keyed cache for optimized pictures and descriptions, with
  a Clear cache action and visible "from cache" marks.
- Measurements per describe: fast and careful look times, tokens
  before and after, file sizes before and after.
- One window with a menu bar, How to Use window, status bar,
  drag and drop, single instance, and remembered window size.
- Command line: optimize, describe, cache-clear, debug-report.
- Debug log layer: rotating log, recent-actions record, scrubbed
  debug report on demand and on crash.
- Double-click GUI installer with a private tools folder, app
  menu entry, desktop icon, and uninstaller.
