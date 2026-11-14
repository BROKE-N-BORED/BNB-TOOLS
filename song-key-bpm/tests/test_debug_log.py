"""Debug log layer tests: wiring, scrubbing, crash hook.

The debug_log.py module is a verbatim copy of the T21 layer; these
tests prove THIS app wires it right: app name and version in the
report, no network and no services, no secret ever reaches the
log or the report.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from songkey.debug_log import DebugLogger, scrub_text  # noqa: E402
from songkey.logsetup import make_logger  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")


def _close(logger):
    for handler in list(logger.logger.handlers):
        handler.close()
        logger.logger.removeHandler(handler)


class DebugLogWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = os.path.join(self.tmp.name, "logs")
        self._loggers = []

    def tearDown(self):
        for logger in self._loggers:
            _close(logger)
        self.tmp.cleanup()

    def _tracked(self, logger):
        self._loggers.append(logger)
        return logger

    def test_debug_log_module_is_the_verbatim_layer(self):
        path = os.path.join(TREE, "songkey", "debug_log.py")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_DEBUG_LOG_SHA256)

    def test_make_logger_registers_version_and_no_services(self):
        logger = self._tracked(make_logger(
            log_dir_path=self.log_dir))
        self.assertEqual(logger.app_name, "song-key-bpm")
        self.assertEqual(logger.version, "0.1.0")
        self.assertEqual(logger.settings.get("app_version"), "0.1.0")
        self.assertIn("network and services", logger.services)
        status = logger.services["network and services"]()
        self.assertIn("no network and no services", status)
        for dep in ("aubio", "miniaudio", "numpy"):
            self.assertIn(dep, logger.dependencies)

    def test_report_filename_uses_app_name(self):
        logger = self._tracked(DebugLogger(
            "song-key-bpm", "0.1.0", log_dir=self.log_dir))
        name = logger.report_filename()
        self.assertTrue(name.startswith("debug-report-song-key-bpm-"))
        self.assertTrue(name.endswith(".txt"))

    def test_report_carries_context_and_no_services(self):
        logger = self._tracked(make_logger(
            log_dir_path=self.log_dir))
        text = logger.build_report()
        self.assertIn("song-key-bpm 0.1.0", text)
        self.assertIn("app_version: 0.1.0", text)
        self.assertIn("no network and no services", text)
        self.assertIn("== Context ==", text)
        self.assertIn("== Recent actions", text)
        self.assertIn("== Errors ==", text)

    def test_crash_hook_writes_a_report(self):
        logger = self._tracked(DebugLogger(
            "song-key-bpm", "0.1.0", log_dir=self.log_dir))
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
        self.logger = DebugLogger("song-key-bpm", "0.1.0",
                                  log_dir=self.log_dir)

    def tearDown(self):
        _close(self.logger)
        self.tmp.cleanup()

    def _log_contents(self):
        with open(self.logger.log_path,
                  encoding="utf-8") as fh:
            return fh.read()

    def test_layer_scrub_text_redacts_password_shape(self):
        scrubbed = scrub_text("password=hunter2")
        self.assertNotIn("hunter2", scrubbed)
        self.assertIn("[REDACTED]", scrubbed)

    def test_logged_password_never_reaches_log_or_report(self):
        self.logger.info("password=hunter2")
        self.assertNotIn("hunter2", self._log_contents())
        self.assertNotIn("hunter2", self.logger.build_report())


if __name__ == "__main__":
    unittest.main()
