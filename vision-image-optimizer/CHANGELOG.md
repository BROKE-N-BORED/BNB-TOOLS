# Changelog

## v0.1.0 — 2026-11-14

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
