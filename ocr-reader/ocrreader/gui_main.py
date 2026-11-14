"""Open the OCR Reader window: python -m ocrreader.gui_main.

The GUI import is guarded: a missing PySide6 shows a
plain-language message pointing at the installer, never a
traceback. The CLI entry stays ocrreader/__main__.py
(python -m ocrreader); this module is the window only.

--help answers without importing Qt, so the launcher answers
even on a machine where the toolkit is missing.
"""

import sys

USAGE = """OCR Reader: read the text out of screenshots and scans,
on this machine, with no network.

Usage:
  ocr-reader            open the window
  ocr-reader --help     show this help

The window reads image files (PNG, JPEG, TIFF, BMP, GIF, WebP)
and PDF files and shows the text it finds. The terminal commands do the same
work without a window: ocr-read reads pictures, ocr-clean tidies
a text file, ocrreader-cli carries every command. Run any of
them with --help for its options.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0
    try:
        from . import gui
    except ImportError:
        print("OCR Reader is missing its interface "
              "toolkit. Double-click Install OCR Reader "
              "to install it.", file=sys.stderr)
        return 1
    return gui.run_gui()


if __name__ == "__main__":
    sys.exit(main())
