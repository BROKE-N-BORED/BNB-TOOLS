"""Debug log layer tests: wiring, scrubbing, crash hook.

The debug_log.py module is a verbatim copy of the T21 layer; these
tests prove THIS app wires it right: app name and version in the
report, the GitHub API as the one service to check, and no secret
ever reaching the log or the report.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (FAKE_GITHUB, FAKE_PASSWORD,  # noqa: E402
                     FAKE_SK)
from board import cli  # noqa: E402
from board.debug_log import DebugLogger, scrub_text  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        handler.close()
        logger.logger.removeHandler(handler)


class DebugLogWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = os.path.join(self.tmp.name, "logs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_debug_log_module_is_the_verbatim_layer(self):
        path = os.path.join(TREE, "board", "debug_log.py")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_DEBUG_LOG_SHA256)

    def test_make_logger_registers_version_org_and_service(self):
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp.name,
                                                   "data")
        logger = cli.make_logger()
        try:
            self.assertEqual(logger.app_name, "repo-health-board")
            self.assertEqual(logger.version, "0.1.0")
            self.assertEqual(logger.settings.get("app_version"),
                             "0.1.0")
            self.assertEqual(logger.settings.get("org"),
                             "BROKE-N-BORED")
            self.assertIn("GitHub API", logger.services)
        finally:
            _close_logger(logger)
            if old is None:
                del os.environ["XDG_DATA_HOME"]
            else:
                os.environ["XDG_DATA_HOME"] = old

    def test_report_filename_uses_app_name(self):
        logger = DebugLogger("repo-health-board", "0.1.0",
                             log_dir=self.log_dir)
        try:
            name = logger.report_filename()
            self.assertTrue(
                name.startswith("debug-report-repo-health-board-"))
            self.assertTrue(name.endswith(".txt"))
        finally:
            _close_logger(logger)

    def test_report_carries_traceback_for_a_logged_exception(self):
        logger = DebugLogger("repo-health-board", "0.1.0",
                             log_dir=self.log_dir)
        try:
            logger.action("refresh started for org TEST-ORG")
            try:
                raise RuntimeError("fake refresh failure")
            except RuntimeError:
                logger.exception("refresh failed")
            text = logger.build_report()
            self.assertIn("repo-health-board 0.1.0", text)
            self.assertIn("Traceback (most recent call last)", text)
            self.assertIn("fake refresh failure", text)
            self.assertIn("refresh started for org TEST-ORG", text)
            self.assertIn("== Context ==", text)
            self.assertIn("== Recent actions", text)
            self.assertIn("== Errors ==", text)
        finally:
            _close_logger(logger)

    def test_crash_hook_writes_a_report(self):
        logger = DebugLogger("repo-health-board", "0.1.0",
                             log_dir=self.log_dir)
        previous = sys.excepthook
        sys.excepthook = lambda *args: None
        try:
            logger.install_crash_handler()
            try:
                raise RuntimeError("fake crash for the test")
            except RuntimeError:
                exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
        finally:
            logger.uninstall_crash_handler()
            sys.excepthook = previous
            _close_logger(logger)
        reports = [name for name in os.listdir(self.log_dir)
                   if name.startswith("debug-report-")]
        self.assertEqual(len(reports), 1)
        content = Path(os.path.join(self.log_dir, reports[0])).read_text(
            encoding="utf-8")
        self.assertIn("fake crash for the test", content)


class LogScrubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = os.path.join(self.tmp.name, "logs")
        self.logger = DebugLogger("repo-health-board", "0.1.0",
                                  log_dir=self.log_dir)

    def tearDown(self):
        _close_logger(self.logger)
        self.tmp.cleanup()

    def _log_contents(self):
        with open(self.logger.log_path,
                  encoding="utf-8") as fh:
            return fh.read()

    def test_layer_scrub_text_redacts_known_shapes(self):
        self.assertNotIn(FAKE_GITHUB,
                         scrub_text("token " + FAKE_GITHUB))
        self.assertNotIn(FAKE_SK, scrub_text("key " + FAKE_SK))
        self.assertNotIn(FAKE_PASSWORD,
                         scrub_text("password=" + FAKE_PASSWORD))

    def test_logged_fake_secrets_never_reach_log_or_report(self):
        self.logger.info("saw token %s", FAKE_GITHUB)
        self.logger.action("key was " + FAKE_SK)
        self.logger.info("password=" + FAKE_PASSWORD)
        for handler in self.logger.logger.handlers:
            handler.flush()
        log_text = self._log_contents()
        for fake in (FAKE_GITHUB, FAKE_SK, FAKE_PASSWORD):
            self.assertNotIn(fake, log_text)
        path = self.logger.generate_report()
        report_text = Path(path).read_text(encoding="utf-8")
        for fake in (FAKE_GITHUB, FAKE_SK, FAKE_PASSWORD):
            self.assertNotIn(fake, report_text)


if __name__ == "__main__":
    unittest.main()
