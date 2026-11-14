#!/usr/bin/env python3
"""Smoke test for T24 staging-guard.

No network, no live repo: fixture dirs are built in a temp directory.
Run from the tool folder:  python3 -m unittest discover -s tests -v
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "staging_guard.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, timeout=60,
    )


class StagingGuardSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base / "main-clone"
        self.staging = base / "publish"
        self.source.mkdir()
        self.staging.mkdir()
        # Fixture "installer" files plus ordinary tree files.
        self.required = ["install.sh", "run.sh", "INSTALL.txt"]
        for name in self.required + ["app.py", "README.md"]:
            (self.source / name).write_text("contents of %s\n" % name)
            (self.staging / name).write_text("contents of %s\n" % name)
        self.manifest = base / "required.json"
        result = run_cli("manifest", "--source", str(self.source),
                         "--files", *self.required,
                         "--out", str(self.manifest))
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, *extra):
        return run_cli("check", "--staging", str(self.staging),
                       "--manifest", str(self.manifest), *extra)

    def test_manifest_hashes_match_source(self):
        data = json.loads(self.manifest.read_text())
        self.assertEqual(sorted(data["files"]), sorted(self.required))
        for name in self.required:
            expected = hashlib.sha256(
                ("contents of %s\n" % name).encode()).hexdigest()
            self.assertEqual(data["files"][name], expected)

    def test_clean_staging_passes(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("STAGING CHECK PASSED", result.stdout)
        self.assertIn("(5 files)", result.stdout)

    def test_missing_file_fails_and_names_it(self):
        (self.staging / "run.sh").unlink()
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL: MISSING: run.sh", result.stdout)
        self.assertIn("STAGING CHECK FAILED", result.stdout)

    def test_changed_file_fails_and_names_it(self):
        (self.staging / "install.sh").write_text("tampered\n")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL: CHANGED: install.sh", result.stdout)

    def test_min_files_gate(self):
        ok = self.check("--min-files", "5")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        short = self.check("--min-files", "6")
        self.assertEqual(short.returncode, 1)
        self.assertIn("FAIL: TOO FEW FILES", short.stdout)

    def test_manifest_refuses_incomplete_source(self):
        result = run_cli("manifest", "--source", str(self.source),
                         "--files", "no-such-file.sh",
                         "--out", str(self.tmp.name) + "/bad.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no-such-file.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
