"""Debug log tests: the copied T21 layer is unmodified, and the
logger wiring produces a report with the FUSE check."""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from appimagehelper import logsetup  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# T21 debug-log-layer/debug_log.py, verified 2026-11-18.
T21_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")


class UnmodifiedCopyTests(unittest.TestCase):

    def test_debug_log_matches_t21_hash(self):
        path = os.path.join(ROOT, "appimagehelper", "debug_log.py")
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(digest, T21_DEBUG_LOG_SHA256)


class LoggerWiringTests(unittest.TestCase):

    def test_report_includes_fuse_check(self):
        tmp = tempfile.mkdtemp(prefix="appimage-log-")
        logger = logsetup.make_logger(log_dir_path=tmp)
        logger.action("test action")
        report = logger.generate_report()
        self.assertTrue(os.path.isfile(report))
        with open(report, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("appimage-run-helper", text)
        self.assertIn("0.1.0", text)
        self.assertIn("FUSE", text)
        self.assertIn("app_version", text)

    def test_logger_writes_log_file(self):
        tmp = tempfile.mkdtemp(prefix="appimage-log-")
        logger = logsetup.make_logger(log_dir_path=tmp)
        logger.action("hello")
        self.assertTrue(os.path.isfile(
            os.path.join(tmp, "appimage-run-helper.log")))


if __name__ == "__main__":
    unittest.main()
