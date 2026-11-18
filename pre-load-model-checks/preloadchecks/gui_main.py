"""Open the kill-picker window: python -m preloadchecks.gui_main.

The GUI import is guarded: a missing PySide6 shows a
plain-language message pointing at the installer, never a
traceback. The CLI entry stays preloadchecks/__main__.py
(python -m preloadchecks); this module is the window only.

--help answers without importing Qt, so the launcher answers
even on a machine where the toolkit is missing.
"""

import sys

USAGE = """Pre-Load Model Checks: check before a model is loaded.

Usage:
  kill-picker                  open the picker window
  kill-picker --require 4.5GB  show whether a 4.5 GB model fits
  kill-picker --dry-run        stop nothing, just say what would be stopped
  kill-picker --help           show this help

The window lists the heaviest running processes (at most 6)
with checkboxes. Tick the ones you do not need and press Kill
selected: only the ones you ticked are stopped, and only after
you confirm. The system itself and this tool are never listed.

The terminal commands do the same checks without a window:
ram-check, process-check, suitability-check, model-watchdog.
Run any of them with --help for its options.
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0
    try:
        from . import gui
    except ImportError:
        print("Pre-Load Model Checks is missing its interface "
              "toolkit. Double-click Install Pre-Load Model "
              "Checks to install it.", file=sys.stderr)
        return 1
    return gui.run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
