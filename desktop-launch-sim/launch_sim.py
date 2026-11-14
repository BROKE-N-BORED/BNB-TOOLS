#!/usr/bin/env python3
"""T25 — desktop-launch-sim.

Simulate what happens when the user double-clicks an installed .desktop
launcher: place the launcher in a different folder from the program
(simulating the Desktop), launch it from an unrelated working directory
with %k expanded to the placed path, and report whether the app actually
starts.

Why: ACR v0.8 shipped a desktop icon that did nothing when clicked — the
icon sat on the Desktop and looked for the program next to itself, while
the program was in the folder the user unzipped. The app runs fine from
its own folder, so no unzip or clone check caught it. This simulation
catches exactly that failure before shipping.

Outcomes:
  STARTED — the process is still running at the end of the probe window
            (a GUI app that stays up). Pass.
  FAILED  — the process exited quickly with a nonzero code (or could not
            be started at all). The report includes the exit code and
            the tail of stderr, so the cause is visible.
  No Exec= line in the .desktop file is a usage error, not a FAILED.

Options:
  --expect-marker PATH   additionally require that this file exists after
                         the probe window — proves the app actually ran
                         its startup code, not just that some process
                         stayed alive.
  --probe-seconds N      how long to watch the process (default 3).
  --timeout N            hard kill timeout for the whole run (default
                         probe-seconds + 5).

Stdlib only. No network, no display needed (the smoke test uses Python
stub apps). The launched command is run WITHOUT a shell (shlex split),
from an unrelated cwd, with %k expanded to the placed .desktop path —
the same expansion a desktop environment performs.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


class LaunchSimError(Exception):
    """Usage error: the .desktop file or arguments are unusable."""


def parse_desktop_exec(path):
    """Return the Exec= value from a .desktop file, or None.

    Only the [Desktop Entry] section is read. Comment lines and other
    sections are ignored. The value is returned verbatim (no unquoting);
    shlex handles quoting at launch time.
    """
    in_entry = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_entry = stripped == "[Desktop Entry]"
                continue
            if not in_entry or not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("Exec="):
                return stripped[len("Exec="):].strip()
    return None


def expand_field_codes(exec_value, desktop_path):
    """Expand the %k field code to the placed .desktop path.

    Other field codes (%f, %F, %u, %U, %i, %c) are dropped — a launcher
    under test takes no files or URLs. %% collapses to a literal %.
    """
    out = []
    i = 0
    while i < len(exec_value):
        ch = exec_value[i]
        if ch == "%" and i + 1 < len(exec_value):
            code = exec_value[i + 1]
            if code == "k":
                out.append(desktop_path)
            elif code == "%":
                out.append("%")
            # Any other field code: drop it (no file/URL arguments).
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def simulate(desktop_src, probe_seconds=3.0, timeout=None,
             expect_marker=None):
    """Run one launch simulation. Returns (outcome, detail).

    outcome is "STARTED" or "FAILED". detail is a human-readable string
    with the exit code and stderr tail on failure.
    """
    if timeout is None:
        timeout = probe_seconds + 5.0
    exec_value = parse_desktop_exec(desktop_src)
    if not exec_value:
        raise LaunchSimError(
            "no Exec= line in %s" % desktop_src)

    tmp = tempfile.mkdtemp(prefix="launch-sim-")
    try:
        place_dir = os.path.join(tmp, "desktop")
        work_dir = os.path.join(tmp, "elsewhere")
        os.makedirs(place_dir)
        os.makedirs(work_dir)
        placed = os.path.join(place_dir, os.path.basename(desktop_src))
        shutil.copy2(desktop_src, placed)

        expanded = expand_field_codes(exec_value, placed)
        try:
            argv = shlex.split(expanded)
        except ValueError as exc:
            return "FAILED", "Exec line does not parse: %s" % exc
        if not argv:
            return "FAILED", "Exec line is empty after expansion"

        try:
            proc = subprocess.Popen(
                argv, cwd=work_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, ValueError) as exc:
            return "FAILED", "could not start %r: %s" % (argv[0], exc)

        deadline = time.time() + probe_seconds
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is None:
            # Still running at the end of the probe window: started.
            if expect_marker is not None and not os.path.exists(
                    expect_marker):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return ("FAILED",
                        "process stayed up but marker %s was never "
                        "written" % expect_marker)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            return "STARTED", "process still running after %.1fs" % (
                probe_seconds,)
        # Exited during the probe window.
        try:
            _out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            _out, err = proc.communicate()
        code = proc.returncode
        tail = err.decode("utf-8", errors="replace").strip().splitlines()
        tail = "\n".join(tail[-5:]) if tail else "(no stderr)"
        if code == 0:
            return ("FAILED",
                    "process exited immediately with code 0 (a GUI app "
                    "that quits at once is not a launch)\n%s" % tail)
        return ("FAILED",
                "process exited with code %d\n%s" % (code, tail))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Simulate a desktop double-click on a .desktop "
                    "launcher placed away from its program.")
    parser.add_argument("desktop", help="path to the .desktop file")
    parser.add_argument("--probe-seconds", type=float, default=3.0,
                        help="how long to watch the process (default 3)")
    parser.add_argument("--timeout", type=float, default=None,
                        help="hard kill timeout (default probe + 5s)")
    parser.add_argument("--expect-marker", default=None,
                        help="file the app must write to count as "
                             "started")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.desktop):
        print("launch-sim: no such file: %s" % args.desktop,
              file=sys.stderr)
        return 2
    try:
        outcome, detail = simulate(
            args.desktop, probe_seconds=args.probe_seconds,
            timeout=args.timeout, expect_marker=args.expect_marker)
    except LaunchSimError as exc:
        print("launch-sim: %s" % exc, file=sys.stderr)
        return 2
    print("%s: %s" % (outcome, detail))
    return 0 if outcome == "STARTED" else 1


if __name__ == "__main__":
    sys.exit(main())
