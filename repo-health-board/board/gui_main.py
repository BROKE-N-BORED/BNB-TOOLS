"""Open the Repo Health Board window: python -m board.gui_main.

The GUI import is guarded: a missing PySide6 shows a
plain-language message pointing at the installer, never a
traceback. The CLI entry stays board/__main__.py (python -m
board); this module is the window only.
"""

import sys


def main(argv=None):
    try:
        from . import gui
    except ImportError:
        print("Repo Health Board is missing its interface "
              "toolkit. Double-click Install Repo Health Board "
              "to install it.", file=sys.stderr)
        return 1
    return gui.run_gui()


if __name__ == "__main__":
    sys.exit(main())
