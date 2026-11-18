"""Command line for Pre-Load Model Checks.

Subcommands (each also has its own wrapper script):
  ram           check free RAM against a model size
  processes     list the top conflicting processes
  suitability   check a model card against the job
  kill          stop only the PIDs listed, with --confirm
  watchdog      run a command, stop it if it goes quiet
  debug-report  print the debug report (T21 layer)
"""

import argparse
import json
import os
import sys

from . import __version__, ram as ram_mod
from . import killer, processes as proc_mod, suitability, watchdog


def _ram(args):
    try:
        required = ram_mod.parse_size(args.require)
    except ValueError:
        print("That size does not make sense: %r. Try something "
              "like 4.5GB or 4096 MB." % args.require,
              file=sys.stderr)
        return 2
    reserve = ram_mod.DEFAULT_RESERVE_BYTES
    if args.reserve is not None:
        try:
            reserve = ram_mod.parse_size(args.reserve)
        except ValueError:
            print("That reserve does not make sense: %r. Try "
                  "something like 1GB." % args.reserve,
                  file=sys.stderr)
            return 2
    try:
        result = ram_mod.check(required, reserve)
    except OSError as exc:
        print("Could not read the memory info: %s"
              % (exc.strerror or exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({
            "required_gb": round(result["required"] / 1024.0 ** 3, 2),
            "reserve_gb": round(result["reserve"] / 1024.0 ** 3, 2),
            "available_gb": round(result["available"] / 1024.0 ** 3, 2),
            "total_gb": round(result["total"] / 1024.0 ** 3, 2),
            "fits": result["fits"],
        }, indent=2))
    else:
        print(ram_mod.plain_report(result), end="")
    return 0 if result["fits"] else 1


def _processes(args):
    limit = args.limit
    if limit < 1 or limit > 20:
        print("The limit must be between 1 and 20.",
              file=sys.stderr)
        return 2
    found = proc_mod.collect(
        sample_interval=args.sample_interval)
    own_tree = killer.own_tree_pids()
    uid = os.getuid()
    top = proc_mod.top_conflicts(
        found, limit=limit, uid=uid, exclude_pids=own_tree,
        killable_only=args.killable_only)
    if args.json:
        print(proc_mod.format_json(top), end="")
    else:
        print(proc_mod.format_plain(top, uid=uid), end="")
    return 0


def _suitability(args):
    try:
        card = suitability.load_json_file(args.card, "model card")
    except suitability.BadInput as exc:
        print(str(exc) + ".", file=sys.stderr)
        return 2
    if args.task:
        try:
            task = suitability.load_json_file(args.task, "task")
        except suitability.BadInput as exc:
            print(str(exc) + ".", file=sys.stderr)
            return 2
    else:
        task = {}
        if args.needs_capability:
            task["needs_capabilities"] = args.needs_capability
        if args.min_context is not None:
            task["min_context_tokens"] = args.min_context
        if args.max_size is not None:
            try:
                task["max_size_gb"] = (
                    ram_mod.parse_size(args.max_size) / 1024.0 ** 3)
            except ValueError:
                print("That size does not make sense: %r. Try "
                      "something like 6GB." % args.max_size,
                      file=sys.stderr)
                return 2
    available = None
    if args.check_ram:
        try:
            available = ram_mod.available_bytes()
        except OSError as exc:
            print("Could not read the memory info: %s"
                  % (exc.strerror or exc), file=sys.stderr)
            return 1
    try:
        ok, problems, warnings = suitability.check_suitability(
            card, task, available_bytes=available)
    except suitability.BadInput as exc:
        print(str(exc) + ".", file=sys.stderr)
        return 2
    name = card.get("name") or "This model"
    if args.json:
        print(json.dumps({
            "model": name,
            "suitable": ok,
            "problems": problems,
            "warnings": warnings,
        }, indent=2))
    else:
        print(suitability.plain_report(name, ok, problems, warnings),
              end="")
    return 0 if ok else 1


def _kill(args):
    if not args.pid:
        print("Give at least one process to stop: "
              "kill --pid 1234 --confirm", file=sys.stderr)
        return 2
    if not args.confirm and not args.dry_run:
        print("Stopping a process needs --confirm. Run it again "
              "with --confirm, or use --dry-run to see what "
              "would be stopped first.", file=sys.stderr)
        return 2
    results = killer.kill_pids(args.pid, confirm=args.confirm,
                               dry_run=args.dry_run)
    print(killer.plain_report(results), end="")
    failed = [r for r in results
              if r["outcome"] in ("refused", "failed")]
    return 1 if failed else 0


def _watchdog(args):
    if not args.watch_command:
        print("Give a command to watch: watchdog --quiet-seconds "
              "60 -- ollama run example", file=sys.stderr)
        return 2
    if args.quiet_seconds < 1:
        print("The quiet time must be at least 1 second.",
              file=sys.stderr)
        return 2
    return watchdog.run(args.watch_command, args.quiet_seconds)


def _debug_report(_args):
    from .logsetup import make_logger
    logger = make_logger()
    print(logger.build_report())
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="preloadchecks-cli",
        description="Check before a model is loaded: RAM, "
                    "conflicting processes, and whether the "
                    "model can do the job.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_ram = sub.add_parser(
        "ram", help="check free RAM against a model size")
    p_ram.add_argument("--require", required=True,
                       help="model size, e.g. 4.5GB")
    p_ram.add_argument("--reserve", default=None,
                       help="RAM kept back for the system "
                            "(default 1GB, 0 to keep none)")
    p_ram.add_argument("--json", action="store_true",
                       help="print the result as JSON")
    p_ram.set_defaults(func=_ram)

    p_proc = sub.add_parser(
        "processes",
        help="list the top conflicting processes")
    p_proc.add_argument("--limit", type=int, default=6,
                        help="how many to list (default 6, max 20)")
    p_proc.add_argument("--killable-only", action="store_true",
                        help="only processes you can stop")
    p_proc.add_argument("--sample-interval", type=float, default=0.5,
                        help="seconds between CPU samples "
                             "(default 0.5)")
    p_proc.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    p_proc.set_defaults(func=_processes)

    p_suit = sub.add_parser(
        "suitability",
        help="check a model card against the job")
    p_suit.add_argument("--card", required=True,
                        help="model card JSON file")
    p_suit.add_argument("--task", default=None,
                        help="task requirements JSON file")
    p_suit.add_argument("--needs-capability", action="append",
                        default=None,
                        help="a capability the job needs "
                             "(repeatable; used when --task is "
                             "not given)")
    p_suit.add_argument("--min-context", type=int, default=None,
                        help="smallest context the job needs, "
                             "in tokens")
    p_suit.add_argument("--max-size", default=None,
                        help="biggest model allowed, e.g. 6GB")
    p_suit.add_argument("--check-ram", action="store_true",
                        help="also check the model fits in RAM")
    p_suit.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    p_suit.set_defaults(func=_suitability)

    p_kill = sub.add_parser(
        "kill", help="stop only the processes listed")
    p_kill.add_argument("--pid", type=int, action="append",
                        default=[], help="PID to stop (repeatable)")
    p_kill.add_argument("--confirm", action="store_true",
                        help="actually stop them (required "
                             "unless --dry-run)")
    p_kill.add_argument("--dry-run", action="store_true",
                        help="say what would be stopped, stop "
                             "nothing")
    p_kill.set_defaults(func=_kill)

    p_watch = sub.add_parser(
        "watchdog",
        help="run a command, stop it if it goes quiet")
    p_watch.add_argument("--quiet-seconds", type=int, default=60,
                         help="seconds of silence before stopping "
                              "it (default 60)")
    p_watch.add_argument("watch_command", nargs=argparse.REMAINDER,
                         help="the command to watch")
    p_watch.set_defaults(func=_watchdog)

    p_debug = sub.add_parser(
        "debug-report", help="print the debug report")
    p_debug.set_defaults(func=_debug_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # argparse.REMAINDER keeps a leading "--" when the user
    # writes `watchdog -- command...`; drop it.
    if getattr(args, "command", None) == "watchdog":
        if args.watch_command and args.watch_command[0] == "--":
            args.watch_command = args.watch_command[1:]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
