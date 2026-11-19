"""Open the AppImage Runner window: python -m appimagehelper.gui_main.

The GUI import is guarded: a missing PySide6 shows a
plain-language message pointing at the installer, never a
traceback. The CLI entry stays appimagehelper/__main__.py
(python -m appimagehelper); this module is the window only.

--help answers without importing Qt, so the launcher answers
even on a machine where the toolkit is missing.
"""

import sys

USAGE = """AppImage Runner: run an AppImage by clicking, no terminal.

Usage:
  appimage-run            open the window
  appimage-run --help     show this help

The window runs an AppImage: pick the file (or drop it on the
window) and press Run it. The tool makes the file runnable and
then runs it. The terminal commands do the same work without a
window: appimage-make-runnable sets the exec bit,
appimagehelper-cli launch makes it runnable and runs it. Run
any of them with --help for its options.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0
    try:
        from . import gui
    except ImportError:
        print("AppImage Runner is missing its interface "
              "toolkit. Double-click Install AppImage Runner "
              "to install it.", file=sys.stderr)
        return 1
    return gui.run_gui()


if __name__ == "__main__":
    sys.exit(main())
