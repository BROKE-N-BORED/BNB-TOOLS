#!/usr/bin/env python3
"""Smoke test for T12 qt-verification-harness.

--help + --check + a PySide6-free env probe + (if PySide6 is importable in
the picked interpreter) a real offscreen window open/close. Reports honestly
which path ran.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent / "qt_harness.py"


def run(*args, timeout=180):
    return subprocess.run([sys.executable, str(HARNESS), *args],
                          capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    p = run("--check")
    print("== --check exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0:
        fails.append("--check failed")

    # PySide6-free probe: prints the env the harness set, asserts TMPDIR=/tmp
    import tempfile
    probe = Path(tempfile.mkdtemp(prefix="t12-smoke-")) / "env_probe.py"
    probe.write_text(
        "import os\n"
        "print('TMPDIR =', os.environ.get('TMPDIR'))\n"
        "print('QT_QPA_PLATFORM =', os.environ.get('QT_QPA_PLATFORM'))\n"
        "print('LD_LIBRARY_PATH has qt-libs:',\n"
        "      'qt-libs' in os.environ.get('LD_LIBRARY_PATH', ''))\n"
        "assert os.environ.get('TMPDIR') == '/tmp'\n"
        "print('ENV PROBE OK')\n")
    p = run(str(probe))
    print("== env probe exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0 or "ENV PROBE OK" not in p.stdout:
        fails.append("env probe failed: %s" % p.stderr[-500:])

    # Real Qt probe if PySide6 is importable in the picked interpreter
    venv_py = Path.home() / "workspace" / "forge-v2-testenv" / "bin" / "python"
    py = str(venv_py) if venv_py.is_file() else sys.executable
    chk = subprocess.run([py, "-c", "import PySide6; print(PySide6.__version__)"],
                         capture_output=True, text=True, timeout=60)
    if chk.returncode == 0:
        print("== PySide6 IS importable (%s) — running real offscreen probe"
              % chk.stdout.strip())
        p = run(str(HERE / "qt_probe.py"))
        print(p.stdout)
        print(p.stderr[-500:] if p.stderr else "")
        if p.returncode != 0 or "PROBE OK" not in p.stdout:
            fails.append("real Qt offscreen probe failed")
    else:
        print("== PySide6 NOT importable — real-window path skipped "
              "(env probe above is the honest coverage)")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
