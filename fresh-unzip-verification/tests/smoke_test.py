#!/usr/bin/env python3
"""Smoke test for T11 fresh-unzip-verification.

Builds two tiny sample zips in /tmp (correct stored modes, one with a passing
test + entry script, one with a failing test) and runs the harness on each:
the first must go green, the second red.
"""
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "fresh_unzip.py"

PASS_TEST = '''import unittest


class SampleTests(unittest.TestCase):
    def test_adds(self):
        self.assertEqual(1 + 1, 2)
'''
FAIL_TEST = '''import unittest


class SampleTests(unittest.TestCase):
    def test_broken(self):
        self.assertEqual(1 + 1, 3)
'''
ENTRY = "#!/bin/sh\necho sample app\n"


def build_zip(path, test_src, good_modes=True):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data, mode in [
            ("sample-app/run.sh", ENTRY, 0o100755),
            ("sample-app/README.md", "# sample\n", 0o100644),
            ("sample-app/test_sample.py", test_src, 0o100644),
        ]:
            zi = zipfile.ZipInfo(name)
            zi.external_attr = (mode if good_modes else 0o755) << 16
            zf.writestr(zi, data)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


def main():
    fails = []
    tmp = Path(tempfile.mkdtemp(prefix="t11-smoke-"))
    good = tmp / "good.zip"
    bad = tmp / "bad.zip"
    build_zip(good, PASS_TEST)
    build_zip(bad, FAIL_TEST)

    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    p = run(str(good), "--expect", "run.sh", "--expect", "README.md",
            "--entry", "run.sh", "--check-modes")
    print("== good zip exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0 or "RESULT: PASS" not in p.stdout:
        fails.append("good zip should go green")

    p = run(str(bad), "--expect", "run.sh", "--entry", "run.sh",
            "--check-modes")
    print("== bad zip exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode == 0 or "RESULT: FAIL" not in p.stdout:
        fails.append("failing-test zip should go red")
    if "[FAIL] command:" not in p.stdout:
        fails.append("the failing check should be the test command")

    # bad stored modes: entry script stored as bare 0o755 must fail --check-modes
    badmodes = tmp / "badmodes.zip"
    build_zip(badmodes, PASS_TEST, good_modes=False)
    p = run(str(badmodes), "--check-modes", "--no-command")
    print("== bad-modes zip exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode == 0 or "[FAIL] zip modes" not in p.stdout:
        fails.append("bare-0o755 modes should fail --check-modes")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
