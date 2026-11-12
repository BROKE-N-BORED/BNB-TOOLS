#!/usr/bin/env python3
"""T12 — qt-verification-harness (standalone).

One command that sets the known-good Qt test environment and runs a
launch/screenshot/render-grab check. Encodes the recipe from AGENTS.md so
nobody has to re-derive the incantation:

  * LD_LIBRARY_PATH  -> ~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu
  * __EGL_VENDOR_LIBRARY_DIRS -> ~/workspace/qt-libs/root/usr/share/glvnd/egl_vendor.d
  * test venv python -> ~/workspace/forge-v2-testenv/bin/python when present
    (else system python3, with a warning)
  * TMPDIR=/tmp ALWAYS — never the workspace (btrfs inotify is racy: the
    workspace mount delivers spurious duplicate inotify events, which broke
    FileWatcher tests deterministically)
  * QT_QPA_PLATFORM=offscreen by default
  * --opengl mode: xvfb-run -a with xcb instead (QOpenGLWidget has no GL
    context under offscreen; Mesa llvmpipe provides the GL)

The harness takes a target — a Python file or a test command — runs it under
the env, captures output, and reports. If qt-libs or the venv are absent on a
machine, it prints exactly what is missing and points at the README's recipe
instead of failing cryptically.

Usage:
    qt_harness.py probe.py                  # run a python file under the env
    qt_harness.py --command "python -m unittest discover -v"
    qt_harness.py --opengl gl_probe.py      # Xvfb + xcb for OpenGL checks
    qt_harness.py --show-env                # print the env, run nothing
    qt_harness.py --check                   # report what is present/missing

Exit code: the target's exit code (0 = target passed), or 2 for harness
usage errors. Missing qt-libs/venv is a WARNING, not a failure — the target
may still run (e.g. a PySide6-free probe); the report says which path ran.
"""
import argparse
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
QT_LIBS = os.path.join(HOME, "workspace", "qt-libs", "root")
QT_LIBDIR = os.path.join(QT_LIBS, "usr", "lib", "x86_64-linux-gnu")
QT_EGL_VENDORS = os.path.join(QT_LIBS, "usr", "share", "glvnd",
                              "egl_vendor.d")
VENV_PYTHON = os.path.join(HOME, "workspace", "forge-v2-testenv",
                           "bin", "python")
# HOME quirk (AGENTS.md): overriding HOME to a fresh /tmp dir breaks Qt xcb
# plugin init with misleading "missing lib" errors — use the existing
# /tmp/forge-test-home, or the real HOME if it is absent.
TEST_HOME = "/tmp/forge-test-home"


def probe():
    """Return a dict of what the recipe needs and whether it is present."""
    return {
        "qt-libs libdir": os.path.isdir(QT_LIBDIR),
        "qt-libs EGL vendors": os.path.isdir(QT_EGL_VENDORS),
        "test venv python": os.path.isfile(VENV_PYTHON),
        "xvfb-run": shutil.which("xvfb-run") is not None,
        "system python3": shutil.which("python3") is not None,
    }


def missing_report(status):
    lines = []
    if not status["qt-libs libdir"]:
        lines.append(
            "MISSING qt-libs at %s — the EGL/xcb libs extracted from Ubuntu "
            "noble .debs (see README: 'Rebuilding qt-libs'). Qt GUI tests "
            "will fail to start without them." % QT_LIBDIR)
    if not status["qt-libs EGL vendors"]:
        lines.append(
            "MISSING EGL vendor dir at %s — offscreen EGL will not find a "
            "driver." % QT_EGL_VENDORS)
    if not status["test venv python"]:
        lines.append(
            "MISSING test venv python at %s — falling back to system "
            "python3 (PySide6 may not be installed there)." % VENV_PYTHON)
    if not status["xvfb-run"]:
        lines.append("MISSING xvfb-run — --opengl mode cannot run.")
    return lines


def build_env(opengl=False):
    """Build the env dict per the AGENTS.md recipe."""
    env = dict(os.environ)
    status = probe()
    if status["qt-libs libdir"]:
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (QT_LIBDIR + (":" + old if old else ""))
    if status["qt-libs EGL vendors"]:
        env["__EGL_VENDOR_LIBRARY_DIRS"] = QT_EGL_VENDORS
    # TMPDIR=/tmp ALWAYS. Never the workspace — btrfs inotify is racy.
    env["TMPDIR"] = "/tmp"
    if os.path.isdir(TEST_HOME):
        env["HOME"] = TEST_HOME
    if opengl:
        env["QT_QPA_PLATFORM"] = "xcb"
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env, status


def pick_python(status):
    if status["test venv python"]:
        return VENV_PYTHON, "test venv"
    return "python3", "system python3 (venv missing)"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run a Qt probe/test under the known-good Qt test env.")
    ap.add_argument("target", nargs="?",
                    help="Python file to run under the Qt env")
    ap.add_argument("--command",
                    help="test command to run instead of a Python file "
                         "(use {python} for the picked interpreter)")
    ap.add_argument("--opengl", action="store_true",
                    help="OpenGL mode: xvfb-run -a + xcb (QOpenGLWidget has "
                         "no GL context under offscreen)")
    ap.add_argument("--show-env", action="store_true",
                    help="print the env that would be used, run nothing")
    ap.add_argument("--check", action="store_true",
                    help="report what the recipe needs and what is "
                         "present/missing, run nothing")
    ap.add_argument("--timeout", type=int, default=600,
                    help="timeout in seconds for the target")
    args = ap.parse_args(argv)

    env, status = build_env(opengl=args.opengl)
    python, python_note = pick_python(status)

    if args.check or args.show_env:
        print("QT TEST ENV — recipe status")
        print("-" * 60)
        for name, ok in status.items():
            print("  [%s] %s" % ("OK  " if ok else "MISS", name))
        for line in missing_report(status):
            print("  ! " + line)
        print("  python: %s (%s)" % (python, python_note))
        if args.show_env:
            print()
            print("  LD_LIBRARY_PATH=" + env.get("LD_LIBRARY_PATH", ""))
            print("  __EGL_VENDOR_LIBRARY_DIRS="
                  + env.get("__EGL_VENDOR_LIBRARY_DIRS", ""))
            print("  TMPDIR=" + env["TMPDIR"])
            print("  HOME=" + env.get("HOME", ""))
            print("  QT_QPA_PLATFORM=" + env["QT_QPA_PLATFORM"])
        return 0

    if not args.target and not args.command:
        ap.error("give a Python file target or --command")
    if args.target and args.command:
        ap.error("give either a target file or --command, not both")

    if args.opengl and not status["xvfb-run"]:
        print("error: --opengl needs xvfb-run, which is not installed",
              file=sys.stderr)
        return 2

    for line in missing_report(status):
        print("warning: " + line, file=sys.stderr)

    if args.target:
        if not os.path.isfile(args.target):
            print("error: no such file: %s" % args.target, file=sys.stderr)
            return 2
        cmd = [python, args.target]
        label = "%s %s" % (python, args.target)
    else:
        cmd = args.command.format(python=python)
        label = cmd
    if args.opengl:
        cmd = ["xvfb-run", "-a"] + (cmd if isinstance(cmd, list)
                                    else ["sh", "-c", cmd])
        label = "xvfb-run -a " + label

    print("QT HARNESS — running under %s"
          % ("Xvfb + xcb (OpenGL)" if args.opengl else "offscreen"),
          flush=True)
    print("  python: %s (%s)" % (python, python_note), flush=True)
    print("  TMPDIR=/tmp  QT_QPA_PLATFORM=%s" % env["QT_QPA_PLATFORM"],
          flush=True)
    print("  command: %s" % label, flush=True)
    print("-" * 60, flush=True)
    try:
        p = subprocess.run(cmd, env=env, shell=isinstance(cmd, str),
                           timeout=args.timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        print("TIMEOUT after %ds" % args.timeout)
        return 1
    print("-" * 60)
    print("RESULT: %s (exit %d)" % ("PASS" if rc == 0 else "FAIL", rc))
    return rc


if __name__ == "__main__":
    sys.exit(main())
