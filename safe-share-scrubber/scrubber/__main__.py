"""Entry point: `python -m scrubber` opens the window; with arguments
it runs the command line (see `python -m scrubber --help`).
"""

import sys


def main():
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main(sys.argv[1:])
    try:
        from .gui import run_gui
    except ImportError:
        print("Safe Share Scrubber needs its interface toolkit "
              "to open the window.", file=sys.stderr)
        print("Double-click Install Safe Share Scrubber to "
              "install it.", file=sys.stderr)
        return 1
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
