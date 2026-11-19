# Changelog

All notable changes to AppImage Runner are recorded here.
The format is based on Keep a Changelog, and this project
follows plain incrementing versions.

## [0.1.0] - 2026-11-18

First release.

### Added
- `make-runnable`: sets the exec bit on an AppImage (the
  Permissions tick, as a command). Already-runnable files are a
  success. Plain-words failures, never a traceback.
- `launch`: makes the file runnable, runs it detached, and
  waits a moment to catch the app dying the instant it starts.
- The window (`appimage-run`): a thin Qt view over the CLI.
  Pick a file or drop one on the window, press Run it, read the
  plain-words status. The phone-first checklist from the
  2026-11-18 incident sits in the window where it is needed.
- How to Use window and a debug report under the File menu,
  with a FUSE presence check (the first thing to check when an
  AppImage will not start).
- One-click installer (Install AppImage Runner.desktop):
  private venv, interface library, rendered icon, menu entry,
  desktop icon, and the three commands on PATH. A missing FUSE
  library warns in plain words and never fails the install.
- The T21 debug log layer, copied unmodified.
