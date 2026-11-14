"""Open the Song Key BPM window: python -m songkey.gui_main.

The GUI import is guarded: a missing PySide6 shows a
plain-language message pointing at the installer, never a
traceback. The CLI entry stays songkey/__main__.py
(python -m songkey); this module is the window only.

--help answers without importing Qt, so the launcher answers
even on a machine where the toolkit is missing.
"""

import sys

USAGE = """Song Key BPM: find the key and BPM of audio files, on this
machine, with no network.

Usage:
  song-key-bpm            open the window
  song-key-bpm --help     show this help

The window analyzes audio files (WAV, MP3, FLAC, OGG) and shows
each file's BPM and key in a table. The terminal commands do the
same work without a window: song-key-analyze analyzes files,
song-key-export writes a CSV table, songkey-cli carries every
command. Run any of them with --help for its options.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0
    try:
        from . import gui
    except ImportError:
        print("Song Key BPM is missing its interface "
              "toolkit. Double-click Install Song Key BPM "
              "to install it.", file=sys.stderr)
        return 1
    return gui.run_gui()


if __name__ == "__main__":
    sys.exit(main())
