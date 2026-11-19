"""Command line for AppImage Runner.

Subcommands (each runnable alone):

  make-runnable FILE   set the exec bit on an AppImage
  launch FILE          make it runnable, then run it
  debug-report         write a debug report file

--json prints the result as JSON (what the window reads);
without it the commands print plain sentences. Exit 0 on
success, 1 on a plain-words failure, 2 on a usage error.

Standard library only: no interface toolkit needed.
"""

import argparse
import json
import sys

from . import __version__
from .core import AppImageError, launch, make_runnable

USAGE = """AppImage Runner: run an AppImage by clicking, no terminal.

Usage:
  appimagehelper-cli make-runnable FILE   set the exec bit
  appimagehelper-cli launch FILE          make it runnable, then run it
  appimagehelper-cli debug-report         write a debug report file
  appimagehelper-cli --help               show this help
  appimagehelper-cli --version            show the version

make-runnable and launch take --json to print the result as
JSON instead of plain sentences. The one-job commands do the
same work with less typing:

  appimage-make-runnable FILE
  appimage-run                open the window
"""


def _print_result(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if result["command"] == "make-runnable":
        if result["already"]:
            print("%s is already runnable." % result["path"])
        else:
            print("Made %s runnable." % result["path"])
    else:
        name = result["path"]
        if result["running"]:
            print("%s is running now." % name)
        elif result["finished"]:
            print("%s ran and finished." % name)


def _fail(message, as_json, command):
    if as_json:
        print(json.dumps({"command": command, "error": message},
                         indent=2, sort_keys=True))
    else:
        print(message, file=sys.stderr)
    return 1


def _cmd_make_runnable(args):
    try:
        result = make_runnable(args.path)
    except AppImageError as exc:
        return _fail(str(exc), args.json, "make-runnable")
    result = dict(result)
    result["command"] = "make-runnable"
    _print_result(result, args.json)
    return 0


def _cmd_launch(args):
    try:
        result = launch(args.path)
    except AppImageError as exc:
        return _fail(str(exc), args.json, "launch")
    result = dict(result)
    result["command"] = "launch"
    _print_result(result, args.json)
    return 0


def _cmd_debug_report(args):
    from .logsetup import make_logger

    logger = make_logger()
    path = logger.generate_report()
    if args.json:
        print(json.dumps({"command": "debug-report",
                          "path": path, "error": None},
                         indent=2, sort_keys=True))
    else:
        print("Debug report written to %s" % path)
        print("Send it to broke.n.bored.studio@gmail.com if "
              "something is broken.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="appimagehelper-cli",
        description="AppImage Runner: run an AppImage by "
                    "clicking, no terminal.",
        epilog="Run `appimagehelper-cli <command> --help` for "
               "one command's options.")
    parser.add_argument(
        "--version", action="version",
        version="appimagehelper-cli %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_make = sub.add_parser(
        "make-runnable",
        help="set the exec bit on an AppImage")
    p_make.add_argument("path", help="the AppImage file")
    p_make.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    p_make.set_defaults(func=_cmd_make_runnable)

    p_launch = sub.add_parser(
        "launch",
        help="make the AppImage runnable, then run it")
    p_launch.add_argument("path", help="the AppImage file")
    p_launch.add_argument("--json", action="store_true",
                          help="print the result as JSON")
    p_launch.set_defaults(func=_cmd_launch)

    p_report = sub.add_parser(
        "debug-report",
        help="write a debug report file")
    p_report.add_argument("--json", action="store_true",
                          help="print the result as JSON")
    p_report.set_defaults(func=_cmd_debug_report)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
