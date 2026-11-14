"""CLI end to end, run as real subprocesses."""

import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (ALL_FAKES, FAKE_AWS, make_text_file,  # noqa: E402
                     sample_innocent_text,
                     sample_log_with_secrets)

try:
    from PySide6.QtCore import QLockFile
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                                   "config")
        self.env["XDG_CACHE_HOME"] = os.path.join(self.tmp.name,
                                                  "cache")
        self.env["QT_QPA_PLATFORM"] = "offscreen"
        self.env["TMPDIR"] = "/tmp"
        self.log = make_text_file(
            os.path.join(self.tmp.name, "debug.log"),
            sample_log_with_secrets())
        self.clean = make_text_file(
            os.path.join(self.tmp.name, "clean.log"),
            sample_innocent_text())

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, args, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "scrubber"] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def test_help_exits_zero(self):
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("scrub", proc.stdout)
        self.assertIn("debug-report", proc.stdout)

    def test_scrub_help_exits_zero(self):
        proc = self.run_cli(["scrub", "--help"])
        self.assertEqual(proc.returncode, 0)

    def test_no_command_prints_help_and_exits_zero(self):
        # The CLI entry with no subcommand prints help. (The
        # __main__ entry with no args opens the GUI instead; that
        # path is not run here.)
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); "
             "from scrubber.cli import main; sys.exit(main([]))"
             % TREE],
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=120)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("scrub", proc.stdout)

    def test_scrub_writes_safe_copy_and_report(self):
        proc = self.run_cli(["scrub", self.log])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        safe = os.path.join(self.tmp.name, "debug.safe.log")
        report_path = os.path.join(self.tmp.name,
                                   "debug.safe-report.txt")
        self.assertTrue(os.path.exists(safe))
        self.assertTrue(os.path.exists(report_path))
        scrubbed = Path(safe).read_text(encoding="utf-8")
        for fake in ALL_FAKES:
            self.assertNotIn(fake, scrubbed)
        self.assertIn("Safe to share", proc.stdout)
        self.assertIn("Secrets found: 15", proc.stdout)
        self.assertIn("Report written to", proc.stdout)
        self.assertIn(report_path, proc.stdout)
        for fake in ALL_FAKES:
            self.assertNotIn(fake, proc.stdout)
        # The original is untouched.
        self.assertEqual(Path(self.log).read_text(encoding="utf-8"),
                         sample_log_with_secrets())

    def test_scrub_multiple_files(self):
        proc = self.run_cli(["scrub", self.log, self.clean])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "clean.safe.log")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe-report.txt")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "clean.safe-report.txt")))
        self.assertIn("Secrets found: 15", proc.stdout)
        self.assertIn("Secrets found: 0", proc.stdout)

    def test_scrub_binary_file_skipped_plainly(self):
        blob = os.path.join(self.tmp.name, "blob.bin")
        with open(blob, "wb") as fh:
            fh.write(b"binary\x00data")
        proc = self.run_cli(["scrub", blob])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Skipped: binary file", proc.stdout)
        self.assertIn("No safe copy was written.", proc.stdout)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "blob.safe.bin")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "blob.safe-report.txt")))

    def test_scrub_missing_file_exits_nonzero(self):
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["scrub", missing])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("No such file", proc.stderr)

    def test_scrub_missing_file_does_not_block_good_file(self):
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["scrub", missing, self.log])
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))

    def test_debug_report_writes_file_and_prints_path(self):
        proc = self.run_cli(["debug-report"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Debug report written to", proc.stdout)
        reports = glob.glob(os.path.join(
            self.tmp.name, "config", "safe-share-scrubber", "logs",
            "debug-report-safe-share-scrubber-*.txt"))
        self.assertEqual(len(reports), 1)
        self.assertIn(reports[0], proc.stdout)
        content = Path(reports[0]).read_text(encoding="utf-8")
        self.assertIn("safe-share-scrubber", content)
        self.assertIn("app_version: 0.2.0", content)
        self.assertIn("no network and no services", content)

    def test_debug_report_out_flag(self):
        out = os.path.join(self.tmp.name, "my-report.txt")
        proc = self.run_cli(["debug-report", "--out", out])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(out))
        self.assertIn(out, proc.stdout)

    @unittest.skipUnless(HAVE_QT, "PySide6 not installed")
    def test_cli_works_while_gui_lock_held(self):
        # The CLI takes no single-instance lock: it runs fine even
        # with the GUI lock file held by another process.
        lock_dir = os.path.join(self.tmp.name, "cache",
                                "safe-share-scrubber")
        os.makedirs(lock_dir, exist_ok=True)
        lock = QLockFile(os.path.join(lock_dir,
                                      "single-instance.lock"))
        lock.setStaleLockTime(0)
        self.assertTrue(lock.tryLock(0))
        try:
            proc = self.run_cli(["scrub", self.log])
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            lock.unlock()


if __name__ == "__main__":
    unittest.main()
