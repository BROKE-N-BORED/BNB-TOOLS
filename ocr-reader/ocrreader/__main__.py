"""Entry point: `python -m ocrreader` opens the window; with arguments
it runs the command line (see `python -m ocrreader --help`).
"""

import sys


def main():
    if len(sys.argv) > 1:
        try:
            from .cli import main as cli_main
        except ImportError as exc:
            # A missing module: plain words, never a traceback.
            # The installer puts the app in its own venv; a bare
            # tree run has no venv.
            missing = getattr(exc, "name", None) or "a module"
            print("OCR Reader needs %s, which is not installed "
                  "for this Python." % missing, file=sys.stderr)
            print("Double-click Install OCR Reader to install "
                  "the app.", file=sys.stderr)
            return 1
        return cli_main(sys.argv[1:])
    try:
        from . import gui_main
    except ImportError:
        print("OCR Reader needs its interface toolkit to open "
              "the window.", file=sys.stderr)
        print("Run ocr-read from the terminal instead, or "
              "install the app.", file=sys.stderr)
        return 1
    entry = getattr(gui_main, "main", None) or getattr(
        gui_main, "run_gui", None)
    if entry is None:
        print("OCR Reader window entry is missing.",
              file=sys.stderr)
        return 1
    return entry()


if __name__ == "__main__":
    sys.exit(main())
