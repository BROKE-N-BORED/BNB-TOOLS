"""Debug log layer tests: wiring, scrubbing, crash hook.

The debug_log.py module is a verbatim copy of the T21 layer; these
tests prove THIS app wires it right: app name and version in the
report, no services to check, no secret ever reaches the log or the
report.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (FAKE_AWS, FAKE_GITHUB, FAKE_PASSWORD,  # noqa: E402
                     FAKE_SK)
from scrubber import cli  # noqa: E402
from scrubber.debug_log import DebugLogger, scrub_text  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")


class DebugLogWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = os.path.join(self.tmp.name, "logs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_debug_log_module_is_the_verbatim_layer(self):
        path = os.path.join(TREE, "scrubber", "debug_log.py")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_DEBUG_LOG_SHA256)

    def test_make_logger_registers_version_and_no_services(self):
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                                     "config")
        logger = cli.make_logger()
        try:
            self.assertEqual(logger.app_name, "safe-share-scrubber")
            self.assertEqual(logger.version, "0.2.0")
            self.assertEqual(logger.settings.get("app_version"),
                             "0.2.0")
            self.assertIn("network and services", logger.services)
            status = logger.services["network and services"]()
            self.assertIn("no network and no services", status)
        finally:
            for handler in list(logger.logger.handlers):
                handler.close()
                logger.logger.removeHandler(handler)
            if old is None:
                del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_report_filename_uses_app_name(self):
        logger = DebugLogger("safe-share-scrubber", "0.2.0",
                             log_dir=self.log_dir)
        name = logger.report_filename()
        self.assertTrue(
            name.startswith("debug-report-safe-share-scrubber-"))
        self.assertTrue(name.endswith(".txt"))

    def test_report_carries_context_and_no_services(self):
        logger = DebugLogger("safe-share-scrubber", "0.2.0",
                             log_dir=self.log_dir)
        logger.set_setting("app_version", "0.2.0")
        logger.register_service(
            "network and services",
            lambda: "none: this app has no network and no services")
        text = logger.build_report()
        self.assertIn("safe-share-scrubber 0.2.0", text)
        self.assertIn("app_version: 0.2.0", text)
        self.assertIn("no network and no services", text)
        self.assertIn("== Context ==", text)
        self.assertIn("== Recent actions", text)
        self.assertIn("== Errors ==", text)

    def test_crash_hook_writes_a_report(self):
        logger = DebugLogger("safe-share-scrubber", "0.2.0",
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
        self.logger = DebugLogger("safe-share-scrubber", "0.2.0",
                                  log_dir=self.log_dir)

    def tearDown(self):
        for handler in list(self.logger.logger.handlers):
            handler.close()
            self.logger.logger.removeHandler(handler)
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
        # Shapes the layer itself scrubs.
        self.logger.info("saw token %s", FAKE_GITHUB)
        self.logger.action("key was " + FAKE_SK)
        self.logger.info("password=" + FAKE_PASSWORD)
        # Shapes only the app scrubber knows: the app never logs
        # file contents, and user text goes through safe_log_text
        # first (the app scrubber), so an AWS-shaped value in a
        # file name still cannot leak.
        self.logger.info("added file %s",
                         cli.safe_log_text("log-" + FAKE_AWS
                                           + ".txt"))
        for handler in self.logger.logger.handlers:
            handler.flush()
        log_text = self._log_contents()
        for fake in (FAKE_GITHUB, FAKE_SK, FAKE_PASSWORD, FAKE_AWS):
            self.assertNotIn(fake, log_text)
        path = self.logger.generate_report()
        report_text = Path(path).read_text(encoding="utf-8")
        for fake in (FAKE_GITHUB, FAKE_SK, FAKE_PASSWORD, FAKE_AWS):
            self.assertNotIn(fake, report_text)

    def test_safe_log_text_scrubs_with_app_patterns(self):
        scrubbed = cli.safe_log_text("file-" + FAKE_AWS + ".log")
        self.assertNotIn(FAKE_AWS, scrubbed)
        self.assertIn("[REDACTED AWS KEY]", scrubbed)


if __name__ == "__main__":
    unittest.main()
