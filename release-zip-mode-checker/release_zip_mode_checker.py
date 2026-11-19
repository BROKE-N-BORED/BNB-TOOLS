#!/usr/bin/env python3
"""release-zip-mode-checker (BNB-TOOLS T39): is the Release zip safe to upload?

A built Release zip must store its launchers and scripts as
executable, or the program will not run when Joshua extracts it:
a `.desktop` file stored without the exec bit opens in a text
editor instead of launching, and a `.sh` file stored without it
gives "Permission denied". GUI extractors (Thunar, Nemo) read
the mode stored in the zip; the `unzip` CLI is more forgiving,
so a zip that works from the terminal can still fail on a
double-click.

This tool has two chainable pieces, each runnable alone:

  check   read a built zip, list the stored modes of every
          `.sh` and `.desktop` entry, FAIL if any of them is
          not stored 0o100755. Exit 0 pass, 1 bad modes,
          2 could not check.
  fix     rebuild the zip with correct modes: 0o100755 for
          `.sh` and `.desktop` entries, 0o100644 for plain
          files that have no stored Unix mode at all, 0o40755
          for directories. Entries that already carry a Unix
          mode and are not launchers or scripts are left
          alone. Reports every mode it changed.

The check catches the exact failure that shipped OST v22: the
installer.desktop went out non-executable, Joshua double-clicked
it, and a text editor opened. The fixed asset had to be
re-uploaded to the Release. Run this before attaching the zip,
not after.

Stored modes live in the zip entry's external_attr, shifted
right 16 bits, and only mean something when the entry was
created on Unix (create_system 3). A mode of 0o755 with no
file-type bits is NOT 0o100755: it extracts fine under the
`unzip` CLI but GUI extractors drop the execute bit, so the
check fails it. An entry with no stored Unix mode at all
(a zip built on Windows, for example) also fails: nothing in
the zip says it is executable.

Errors are plain words naming the missing thing, never a
traceback.

Usage:
  python3 release_zip_mode_checker.py check <zip>
      [--json] [--debug-report PATH]
  python3 release_zip_mode_checker.py fix <zip>
      [--out PATH] [--in-place] [--debug-report PATH]
  python3 release_zip_mode_checker.py debug-report [--out PATH]
  python3 release_zip_mode_checker.py --version
  python3 release_zip_mode_checker.py --help
"""

import argparse
import datetime
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

VERSION = "0.1.0"
APP_SLUG = "release-zip-mode-checker"
REPORT_EMAIL = "broke.n.bored.studio@gmail.com"

REQUIRED_EXEC = 0o100755
REQUIRED_PLAIN = 0o100644
REQUIRED_DIR = 0o40755
EXEC_SUFFIXES = (".sh", ".desktop")

try:
    from debug_log import DebugLogger
except ImportError:  # the script copied without its debug_log.py
    DebugLogger = None


class CheckError(Exception):
    """A plain-words failure: the check could not run or finish."""


def stored_mode(info):
    """The Unix mode stored for one zip entry, or None.

    Only entries created on Unix (create_system 3) carry a Unix
    mode, in the top 16 bits of external_attr. A zero there means
    no mode was stored at all.
    """
    if info.create_system != 3:
        return None
    mode = (info.external_attr >> 16) & 0o177777
    if mode == 0:
        return None
    return mode


def mode_text(mode):
    """How a stored mode prints: '0o100644', or 'no stored mode'."""
    if mode is None:
        return "no stored mode"
    return "0o%o" % mode


def is_exec_entry(name):
    """True when the entry is a launcher or script that must be
    stored executable: a .sh or .desktop file."""
    return name.lower().endswith(EXEC_SUFFIXES)


def is_dir_entry(info):
    return info.is_dir()


def check_zip(zip_path):
    """Check one zip. Returns a result dict.

    checked: one entry per .sh/.desktop file, each with name,
    mode (int or None), and ok.
    other_files / directories: counts of entries not checked.
    failures: the checked entries that are not 0o100755.
    ok: True when there are no failures.
    Raises CheckError when the zip cannot be read at all.
    """
    path = Path(zip_path)
    if not path.exists():
        raise CheckError("no such file: %s" % zip_path)
    if not path.is_file():
        raise CheckError("not a file: %s" % zip_path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile:
        raise CheckError("not a zip file: %s" % zip_path)
    except OSError as exc:
        raise CheckError("could not read %s (%s)" % (zip_path, exc))
    checked = []
    other_files = 0
    directories = 0
    try:
        infos = zf.infolist()
    except zipfile.BadZipFile:
        raise CheckError("not a zip file: %s" % zip_path)
    finally:
        zf.close()
    for info in infos:
        if is_dir_entry(info):
            directories += 1
            continue
        if not is_exec_entry(info.filename):
            other_files += 1
            continue
        mode = stored_mode(info)
        checked.append({
            "name": info.filename,
            "mode": mode,
            "ok": mode == REQUIRED_EXEC,
        })
    failures = [entry for entry in checked if not entry["ok"]]
    return {
        "zip": str(zip_path),
        "entries": len(infos),
        "checked": checked,
        "other_files": other_files,
        "directories": directories,
        "failures": failures,
        "ok": not failures,
    }


def print_check_text(result):
    """The check result in plain words, to stdout."""
    print("Checking %s (%d %s)..." % (
        result["zip"], result["entries"],
        "entry" if result["entries"] == 1 else "entries"))
    for entry in result["checked"]:
        status = "OK" if entry["ok"] else "FAIL - needs 0o100755"
        print("  %-40s %-14s %s" % (
            entry["name"], mode_text(entry["mode"]), status))
    print("Checked %d %s, %d other %s, %d %s." % (
        len(result["checked"]),
        "launcher/script" if len(result["checked"]) == 1
        else "launchers/scripts",
        result["other_files"],
        "file" if result["other_files"] == 1 else "files",
        result["directories"],
        "directory" if result["directories"] == 1 else "directories"))
    if result["ok"]:
        if result["checked"]:
            print("OK: every .sh and .desktop entry is stored "
                  "executable (0o100755).")
        else:
            print("OK: no .sh or .desktop entries to check.")
    else:
        count = len(result["failures"])
        print("FAIL: %d %s %s the wrong stored mode. Fix it "
              "before uploading the Release." % (
                  count, "entry" if count == 1 else "entries",
                  "has" if count == 1 else "have"))


def print_json(result):
    """The check result as JSON, to stdout. Modes print as
    octal strings ('0o100644') or null when nothing is stored,
    so a reader never has to guess the base."""
    out = {
        "zip": result["zip"],
        "entries": result["entries"],
        "ok": result["ok"],
        "checked": [
            {"name": entry["name"],
             "mode": ("0o%o" % entry["mode"])
             if entry["mode"] is not None else None,
             "ok": entry["ok"]}
            for entry in result["checked"]
        ],
        "other_files": result["other_files"],
        "directories": result["directories"],
        "failures": [entry["name"] for entry in result["failures"]],
    }
    print(json.dumps(out, indent=2))


def fixed_mode(info):
    """The mode fix() stores for one entry, or None to leave it
    exactly as it is.

    Launchers and scripts always get 0o100755. Directories get
    0o40755. Any other file gets 0o100644 only when it has no
    stored Unix mode at all; a file that already carries a Unix
    mode keeps it, so fix never strips an exec bit something
    else put there on purpose.
    """
    mode = stored_mode(info)
    if is_dir_entry(info):
        return None if mode == REQUIRED_DIR else REQUIRED_DIR
    if is_exec_entry(info.filename):
        return None if mode == REQUIRED_EXEC else REQUIRED_EXEC
    if mode is None:
        return REQUIRED_PLAIN
    return None


def fix_zip(src_path, dst_path):
    """Rebuild the zip at src_path with correct stored modes,
    writing to dst_path. Contents, order, compression, dates,
    comments, and extra fields are preserved byte for byte.
    Returns the list of changes: (name, old mode, new mode).
    Raises CheckError when the zip cannot be read or written.
    """
    src = Path(src_path)
    if not src.exists():
        raise CheckError("no such file: %s" % src_path)
    if not src.is_file():
        raise CheckError("not a file: %s" % src_path)
    try:
        zin = zipfile.ZipFile(src, "r")
    except zipfile.BadZipFile:
        raise CheckError("not a zip file: %s" % src_path)
    except OSError as exc:
        raise CheckError("could not read %s (%s)" % (src_path, exc))
    changes = []
    try:
        try:
            infos = zin.infolist()
        except zipfile.BadZipFile:
            raise CheckError("not a zip file: %s" % src_path)
        try:
            zout = zipfile.ZipFile(dst_path, "w",
                                   zipfile.ZIP_DEFLATED)
        except OSError as exc:
            raise CheckError("could not write %s (%s)"
                             % (dst_path, exc))
        with zout:
            zout.comment = zin.comment
            for info in infos:
                new_mode = fixed_mode(info)
                old_mode = stored_mode(info)
                if new_mode is not None:
                    changes.append((info.filename, old_mode,
                                    new_mode))
                new_info = zipfile.ZipInfo(info.filename,
                                           info.date_time)
                new_info.compress_type = info.compress_type
                new_info.comment = info.comment
                new_info.extra = info.extra
                new_info.internal_attr = info.internal_attr
                new_info.create_system = 3
                if new_mode is not None:
                    new_info.external_attr = new_mode << 16
                else:
                    # Kept exactly as stored: fixed_mode only
                    # returns None for an entry that already
                    # carries a Unix mode (create_system 3),
                    # so the copied external_attr is meaningful.
                    new_info.external_attr = info.external_attr
                if is_dir_entry(info):
                    zout.writestr(new_info, b"")
                else:
                    try:
                        data = zin.read(info.filename)
                    except (zipfile.BadZipFile, KeyError,
                            OSError) as exc:
                        raise CheckError(
                            "could not read %s inside %s (%s)"
                            % (info.filename, src_path, exc))
                    zout.writestr(new_info, data)
    finally:
        zin.close()
    return changes


def default_fixed_name(src_path):
    """myapp-v1.0.zip -> myapp-v1.0-modes-fixed.zip, same folder."""
    src = Path(src_path)
    return str(src.with_name("%s-modes-fixed%s"
                             % (src.stem, src.suffix)))


def print_fix_text(src_path, dst_path, changes, total):
    """The fix result in plain words, to stdout."""
    print("Fixed %s -> %s" % (src_path, dst_path))
    for name, old_mode, new_mode in changes:
        print("  %s: %s -> 0o%o"
              % (name, mode_text(old_mode), new_mode))
    unchanged = total - len(changes)
    if changes:
        print("%d %s changed, %d unchanged."
              % (len(changes),
                 "entry" if len(changes) == 1 else "entries",
                 unchanged))
    else:
        print("Nothing to fix: every entry already has the "
              "right stored mode.")


def make_logger(log_dir):
    """The T21 debug log layer, wired to this app.

    Settings: the app version (no secrets ever: this tool has
    no credentials, no network, no services to check). The log
    dir is a temp dir owned by the caller, so no logs/ directory
    is left behind.
    """
    if DebugLogger is None:
        raise CheckError(
            "debug report needs debug_log.py next to this script; "
            "it is missing.")
    logger = DebugLogger(APP_SLUG, VERSION, log_dir=log_dir)
    logger.set_setting("app_version", VERSION)
    return logger


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        try:
            handler.close()
        finally:
            logger.logger.removeHandler(handler)


def _write_debug_report(logger, path):
    try:
        written = logger.generate_report(path)
        print("debug report written to %s" % written,
              file=sys.stderr)
    except OSError as exc:
        print("warning: could not write debug report to %s (%s)"
              % (path, exc), file=sys.stderr)


def cmd_check(args):
    """Run the check. Exit 0 pass, 1 bad modes, 2 no check."""
    logger = None
    tmp = None
    try:
        if args.debug_report:
            tmp = tempfile.TemporaryDirectory(
                prefix="zip-modes.")
            logger = make_logger(tmp.name)
            logger.action("check %s" % args.zip)
        result = check_zip(args.zip)
        if logger is not None:
            logger.action("check done: %s"
                       % ("pass" if result["ok"] else "fail"))
        if args.json:
            print_json(result)
        else:
            print_check_text(result)
        return 0 if result["ok"] else 1
    except CheckError as exc:
        if args.json:
            print(json.dumps({"zip": args.zip, "ok": None,
                              "error": str(exc)}, indent=2))
        else:
            print("error: %s" % exc, file=sys.stderr)
        return 2
    finally:
        if logger is not None and args.debug_report:
            _write_debug_report(logger, args.debug_report)
            _close_logger(logger)
        if tmp is not None:
            tmp.cleanup()


def cmd_fix(args):
    """Run the fix. Exit 0 fixed, 2 could not fix."""
    logger = None
    tmp = None
    try:
        if args.debug_report:
            tmp = tempfile.TemporaryDirectory(
                prefix="zip-modes.")
            logger = make_logger(tmp.name)
            logger.action("fix %s" % args.zip)
        if args.in_place:
            if args.out is not None:
                print("error: --out and --in-place cannot be "
                      "used together; --in-place rewrites the "
                      "zip itself", file=sys.stderr)
                return 2
            dst = None
        elif args.out is not None:
            dst = args.out
            if os.path.abspath(dst) == os.path.abspath(args.zip):
                print("error: refusing to write over the input "
                      "zip; use --in-place to rewrite it, or "
                      "pick a different --out", file=sys.stderr)
                return 2
        else:
            dst = default_fixed_name(args.zip)
        if args.in_place:
            src = Path(args.zip)
            fd, tmp_name = tempfile.mkstemp(
                prefix=src.stem + ".", suffix=".zip",
                dir=str(src.parent))
            os.close(fd)
            try:
                changes = fix_zip(args.zip, tmp_name)
                os.replace(tmp_name, args.zip)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            dst = args.zip
        else:
            changes = fix_zip(args.zip, dst)
        try:
            total = len(zipfile.ZipFile(dst, "r").infolist())
        except (zipfile.BadZipFile, OSError) as exc:
            print("error: the fixed zip %s could not be read "
                  "back (%s)" % (dst, exc), file=sys.stderr)
            return 2
        if logger is not None:
            logger.action("fix done: %d changes" % len(changes))
        print_fix_text(args.zip, dst, changes, total)
        return 0
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: could not fix %s (%s)" % (args.zip, exc),
              file=sys.stderr)
        return 2
    finally:
        if logger is not None and args.debug_report:
            _write_debug_report(logger, args.debug_report)
            _close_logger(logger)
        if tmp is not None:
            tmp.cleanup()


def cmd_debug_report(args):
    """Write a debug report and print its path. Exit 0."""
    if args.out is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        args.out = "debug-report-%s-%s.txt" % (APP_SLUG, stamp)
    try:
        with tempfile.TemporaryDirectory(
                prefix="zip-modes.") as tmp:
            logger = make_logger(tmp)
            try:
                path = logger.generate_report(args.out)
            finally:
                _close_logger(logger)
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: could not write debug report to %s (%s)"
              % (args.out, exc), file=sys.stderr)
        return 2
    print("Debug report written to %s" % path)
    print("Send it to %s if something is broken." % REPORT_EMAIL)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="release_zip_mode_checker.py",
        description="Check and fix the stored modes in a built "
                    "Release zip: .sh and .desktop entries must "
                    "be stored 0o100755.")
    parser.add_argument("--version", action="version",
                        version="release-zip-mode-checker %s"
                        % VERSION)
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser(
        "check", help="check the stored modes in a zip")
    check.add_argument("zip", help="the built zip to check")
    check.add_argument("--json", action="store_true",
                       help="print the result as JSON")
    check.add_argument("--debug-report", default=None,
                       help="also write a debug report to PATH")
    check.set_defaults(func=cmd_check)

    fix = sub.add_parser(
        "fix", help="rebuild a zip with correct stored modes")
    fix.add_argument("zip", help="the built zip to fix")
    fix.add_argument("--out", default=None,
                     help="where to write the fixed zip "
                          "(default: <name>-modes-fixed.zip "
                          "next to the input)")
    fix.add_argument("--in-place", action="store_true",
                     help="rewrite the input zip itself "
                          "(via a temp file, atomically)")
    fix.add_argument("--debug-report", default=None,
                     help="also write a debug report to PATH")
    fix.set_defaults(func=cmd_fix)

    report = sub.add_parser(
        "debug-report", help="write a debug report")
    report.add_argument("--out", default=None,
                        help="where to write the report "
                             "(default: debug-report-"
                             "release-zip-mode-checker-"
                             "<date>-<time>.txt)")
    report.set_defaults(func=cmd_debug_report)
    return parser


def main(argv=None):
    """Dispatch. --help exits 0. No traceback ever reaches the
    user: unexpected errors are reported in plain words, exit 2."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except BrokenPipeError:
        return 2
    except KeyboardInterrupt:
        print("error: stopped by the user.", file=sys.stderr)
        return 2
    except Exception as exc:  # never a traceback, per the spec
        print("error: the check failed unexpectedly (%s). "
              "Run again with --debug-report PATH and send the "
              "report to %s if it keeps happening."
              % (exc, REPORT_EMAIL), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
