#!/usr/bin/env python3
"""Smoke test for T25 desktop-launch-sim.

Three fixtures, all headless Python stubs (no display, no network):

1. Good absolute-path launcher -> STARTED, marker written.
2. Broken %k-relative launcher (the ACR v0.8 bug shape: the program is
   looked up next to the placed icon, where it is not) -> FAILED.
3. .desktop file with no Exec= line -> usage error (exit 2).

Run: python3 tests/smoke_test.py   (from the tool directory, or anywhere)
Exit 0 only if all three fixtures behave as expected.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
LAUNCH_SIM = os.path.join(TOOL_DIR, "launch_sim.py")
PY = sys.executable

STUB_APP = (
    "import sys, time\n"
    "open(sys.argv[1], 'w').write('started\\n')\n"
    "time.sleep(60)\n"
)

# ACR v0.8 bug shape: resolve the program next to the .desktop file
# (%k), which is the placed copy on the simulated Desktop — the program
# is not there, so the exec fails.
BROKEN_ONE_LINER = (
    "import os, sys; d = os.path.dirname(sys.argv[1]); "
    "p = os.path.join(d, 'app.py'); "
    "os.execv(sys.executable, [sys.executable, p])"
)


def run_sim(desktop_path, extra_args=()):
    cmd = [PY, LAUNCH_SIM, desktop_path, "--probe-seconds", "1"]
    cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fixture_good(tmp):
    """Absolute-path launcher pointing at a real stub app."""
    app_dir = os.path.join(tmp, "program")
    os.makedirs(app_dir)
    app = os.path.join(app_dir, "app.py")
    write(app, STUB_APP)
    marker = os.path.join(tmp, "started.marker")
    desktop = os.path.join(tmp, "good.desktop")
    write(desktop,
          "[Desktop Entry]\n"
          "Type=Application\n"
          "Name=Good App\n"
          "Exec=%s %s %s\n" % (PY, app, marker))
    result = run_sim(desktop, ["--expect-marker", marker])
    ok = (result.returncode == 0
          and result.stdout.startswith("STARTED")
          and os.path.isfile(marker))
    return ok, result


def fixture_broken(tmp):
    """%k-relative launcher: program looked up next to the placed icon."""
    desktop = os.path.join(tmp, "broken.desktop")
    write(desktop,
          "[Desktop Entry]\n"
          "Type=Application\n"
          "Name=Broken App\n"
          'Exec=%s -c "%s" %%k\n' % (PY, BROKEN_ONE_LINER))
    result = run_sim(desktop)
    ok = (result.returncode == 1
          and result.stdout.startswith("FAILED"))
    return ok, result


def fixture_no_exec(tmp):
    """.desktop file with no Exec= line at all."""
    desktop = os.path.join(tmp, "noexec.desktop")
    write(desktop,
          "[Desktop Entry]\n"
          "Type=Application\n"
          "Name=No Exec App\n")
    result = run_sim(desktop)
    ok = (result.returncode == 2
          and "no Exec= line" in result.stderr)
    return ok, result


def main():
    fixtures = [
        ("good absolute-path launcher -> STARTED + marker", fixture_good),
        ("broken %k-relative launcher -> FAILED detected",
         fixture_broken),
        ("missing Exec= line -> usage error (exit 2)", fixture_no_exec),
    ]
    failures = 0
    for name, fn in fixtures:
        with tempfile.TemporaryDirectory(prefix="launch-sim-smoke-") as tmp:
            ok, result = fn(tmp)
        status = "PASS" if ok else "FAIL"
        print("%s: %s" % (status, name))
        if not ok:
            failures += 1
            print("  returncode=%s" % result.returncode)
            print("  stdout: %s" % result.stdout.strip())
            print("  stderr: %s" % result.stderr.strip())
    print("%d/%d smoke fixtures passed" % (
        len(fixtures) - failures, len(fixtures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
