"""Entry point: `python -m songkey` opens the window; with arguments
it runs the command line (see `python -m songkey --help`).
"""

import sys


def main():
    if len(sys.argv) > 1:
        try:
            from .cli import main as cli_main
        except ImportError as exc:
            # A missing audio library (aubio or numpy): plain words,
            # never a traceback. The installer puts these in the
            # app's own venv; a bare tree run has no venv.
            missing = getattr(exc, "name", None) or "an audio library"
            print("Song Key BPM needs %s, which is not installed "
                  "for this Python." % missing, file=sys.stderr)
            print("Double-click Install Song Key BPM to install "
                  "the app.", file=sys.stderr)
            return 1
        return cli_main(sys.argv[1:])
    try:
        from . import gui_main
    except ImportError:
        print("Song Key BPM needs its interface toolkit to open "
              "the window.", file=sys.stderr)
        print("Run song-key-analyze from the terminal instead, or "
              "install the app.", file=sys.stderr)
        return 1
    entry = getattr(gui_main, "main", None) or getattr(
        gui_main, "run_gui", None)
    if entry is None:
        print("Song Key BPM window entry is missing.",
              file=sys.stderr)
        return 1
    return entry()


if __name__ == "__main__":
    sys.exit(main())
