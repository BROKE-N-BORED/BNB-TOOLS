# Changelog - T41 manual-pdf-builder

## v0.1.0 - 2026-11-18

First release. Three chainable pieces in one stdlib-only script
(`manual_pdf.py`), each a function and a CLI subcommand:

- `check`: every path, script, and version a MANUAL.md cites
  must exist or match in the project tree; failures are a
  plain-words list with line numbers; unverifiable versions are
  warnings, never silent passes.
- `emdash`: fails the build if the manual contains an em-dash
  or an en-dash.
- `render`: MANUAL.md -> styled HTML -> A4 PDF via a headless
  Chromium binary driven through `--print-to-pdf` (the SOLDAR
  manual's proven pattern; no Playwright package needed). Runs
  the emdash check first.
- `build`: the chain, check then emdash then render, stopping
  at the first failure.
- Missing-Chromium guard: plain words naming what is missing
  and how to get it, exit 1, never a traceback.
- `demo.py` (each piece alone, and the chain), `build_zip.py`
  (release zip with correct stored modes), T21 debug log layer
  (`debug_log.py`, unmodified) behind `debug-report`.
