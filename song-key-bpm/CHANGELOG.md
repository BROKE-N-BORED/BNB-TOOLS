# Changelog

## v0.1.0 - 2026-11-14

First release.

- Measure the BPM and key of audio files (WAV, MP3, FLAC, OGG),
  on the machine, with no network: BPM from the gaps between
  beats, key from the notes matched against the
  Krumhansl-Schmuckler profiles.
- One window with a file list, a results table (File, BPM, Key,
  Confidence, Duration), an Analyze button, an Export button, a
  Cancel button, a menu bar, a How to Use window, a status bar,
  single instance, and remembered window size.
- The honest caveat, stated in the app and the README: BPM is a
  measurement and key is an estimate. Relative major and minor
  pairs share the same notes, so a close call between them is
  normal. Low-confidence keys show the runner-up in the table.
- BPM needs a beat: a file with no beat reports BPM unknown
  instead of a made-up number. A file that cannot be read says
  so in the table.
- Command line: analyze, export, debug-report, plus the
  one-job commands song-key-analyze and song-key-export and the
  window launcher song-key-bpm.
- Export the table as a CSV file, next to your songs or
  wherever you pick.
- Debug log layer: rotating log, recent-actions record, scrubbed
  debug report on demand and on crash.
- Double-click GUI installer with a private tools folder, app
  menu entry, desktop icon, and uninstaller.
