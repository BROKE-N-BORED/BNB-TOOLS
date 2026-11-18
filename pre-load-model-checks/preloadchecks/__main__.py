"""Entry point: `python -m preloadchecks` opens the picker
window; with arguments it runs the command line (see
`python -m preloadchecks --help`).
"""

import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        try:
            from .cli import main as cli_main
        except ImportError as exc:
            # A missing module: plain words, never a traceback.
            missing = getattr(exc, "name", None) or "a module"
            print("Pre-Load Model Checks needs %s, which is not "
                  "installed for this Python." % missing,
                  file=sys.stderr)
            print("Double-click Install Pre-Load Model Checks "
                  "to install the app.", file=sys.stderr)
            return 1
        return cli_main(args)
    try:
        from . import gui_main
    except ImportError:
        print("Pre-Load Model Checks needs its interface toolkit "
              "to open the window.", file=sys.stderr)
        print("Run ram-check, process-check, or "
              "suitability-check from the terminal instead, or "
              "install the app.", file=sys.stderr)
        return 1
    return gui_main.main([])


if __name__ == "__main__":
    sys.exit(main())
