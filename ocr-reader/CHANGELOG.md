# Changelog

## v0.1.0 - 2026-11-14

First release.

- Read the text out of image files (PNG, JPEG, TIFF, BMP, GIF,
  WebP) and PDFs with Tesseract, on the machine, with no
  network. PDFs are read page by page through pdftoppm at
  300 dpi, with a page marker between pages.
- One window with a file list, a text pane, Read, Clean, Copy,
  Save, and Cancel buttons, a menu bar, a How to Use window, a
  status bar, single instance, and remembered window size.
  Selecting a file shows its text; a file that cannot be read
  says so in plain words.
- Clean tidies OCR text without ever rewriting words: trailing
  whitespace, runs of extra spaces, spaces before punctuation,
  wrapped lines joined mid-sentence, blank lines collapsed.
  Cleaning is idempotent.
- The honest caveat, stated in the app and the README: OCR is
  approximate, handwriting and low-contrast images read poorly.
  Check the text before you use it.
- Plain failures everywhere: a missing tesseract, a missing
  pdftoppm, an unreadable file, and a timed-out read all report
  in plain words, never a traceback.
- Command line: read, clean, debug-report, plus the one-job
  commands ocr-read and ocr-clean and the window launcher
  ocr-reader.
- Debug log layer: rotating log, recent-actions record, scrubbed
  debug report on demand and on crash.
- Double-click GUI installer with a private tools folder, app
  menu entry, desktop icon, and uninstaller. The installer
  checks for tesseract first and stops with plain install
  instructions when it is missing.
