# Changelog

## v0.1.0 - 2026-11-15

First release.

- Palette extraction (`photo_palette.py`): sample pixels from
  one or more photos and print a hex list plus CSS variables,
  to stdout or a file (`--out`). Options: `--colors` (default
  12, 1 to 256), `--sample` (default 30000).
- Method: evenly spaced deterministic sampling (the sample
  budget split evenly across photos), median-cut clustering
  via PIL `quantize`, each cluster color snapped to the
  nearest actually sampled color so every hex is a real color
  from the photos, palette ordered most common first. Up to
  the requested count: fewer when the photos hold fewer
  distinct colors, never an invented color.
- Plain-words errors, exit 1, never a traceback: missing
  photo, unreadable photo, bad `--colors` / `--sample`,
  unwritable `--out`. Missing PIL names PIL and says how to
  install it (`python3 -m pip install Pillow`), with a
  regression test (the T31 missing-dependency guard pattern).
  `--help` exits 0 and works without Pillow, as do
  `--version` and `--debug-report`.
- Debug report (`--debug-report`): the T21 debug log layer,
  copied unmodified (SHA-256 pinned in the tests). Normal
  runs never touch it and never create a `logs/` dir.
- 27 tests, no network, no real photos: fixtures generated
  with PIL at test time (solid blocks, two-color split,
  stripes, gradient).
