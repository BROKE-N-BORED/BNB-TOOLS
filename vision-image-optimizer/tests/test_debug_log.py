"""Debug log layer (S61/T21) as wired into this app: scrubbing,
report shape, Ollama status, crash hook, no-clobber reports."""

import glob
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import FakeOllama  # noqa: E402
from optimizer.debug_log import (DebugLogger, check_ollama,  # noqa: E402
                                 scrub_text)

# Deliberate fakes for the scrub test — the packaging test allowlists
# this file only for these patterns.
FAKE_API_KEY = "sk-fake-test-secret-0123456789abcdef"
FAKE_GITHUB_TOKEN = "ghp_fakeTestToken0123456789abcdefghij"
FAKE_PASSWORD = "hunter2-test-password"


class ScrubTests(unittest.TestCase):
    def test_scrub_text_redacts_known_shapes(self):
        self.assertNotIn(FAKE_API_KEY, scrub_text(
            "key is " + FAKE_API_KEY))
        self.assertIn("[REDACTED]", scrub_text(
            "key is " + FAKE_API_KEY))
        self.assertNotIn(FAKE_GITHUB_TOKEN, scrub_text(
            "token " + FAKE_GITHUB_TOKEN))
        self.assertNotIn(FAKE_PASSWORD, scrub_text(
            "password=" + FAKE_PASSWORD))

    def test_report_carries_no_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            logger.info("started with api_key=%s", FAKE_API_KEY)
            logger.info("token %s in use", FAKE_GITHUB_TOKEN)
            logger.set_setting("some_password", FAKE_PASSWORD)
            logger.set_setting("model", "minicpm-v")
            path = logger.generate_report()
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn(FAKE_API_KEY, text)
            self.assertNotIn(FAKE_GITHUB_TOKEN, text)
            self.assertNotIn(FAKE_PASSWORD, text)
            self.assertIn("[REDACTED]", text)
            # Non-secret settings still show.
            self.assertIn("minicpm-v", text)


class ReportTests(unittest.TestCase):
    def test_report_sections_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            logger.action("user pressed Describe")
            logger.info("describe done")
            path = logger.generate_report()
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            sections = ["== Context ==", "== Settings ==",
                        "== Services ==", "== Recent actions",
                        "== Errors ==", "== Log tail"]
            positions = [text.index(s) for s in sections]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("user pressed Describe", text)
            self.assertIn("vision-image-optimizer", text)

    def test_report_filename_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            name = logger.report_filename()
            self.assertTrue(
                name.startswith(
                    "debug-report-vision-image-optimizer-"))
            self.assertTrue(name.endswith(".txt"))

    def test_two_reports_same_second_do_not_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            first = logger.generate_report()
            second = logger.generate_report()
            self.assertNotEqual(first, second)
            self.assertTrue(os.path.exists(first))
            self.assertTrue(os.path.exists(second))

    def test_ollama_status_in_report(self):
        server = FakeOllama().start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                logger = DebugLogger("vision-image-optimizer",
                                     "0.1.0", log_dir=tmp)
                logger.register_service(
                    "ollama",
                    lambda: check_ollama(server.base_url,
                                         timeout=2))
                path = logger.generate_report()
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertIn("running (2 model(s)", text)
                self.assertIn("minicpm-v", text)
        finally:
            server.stop()

    def test_ollama_down_in_report(self):
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            logger.register_service(
                "ollama",
                lambda: check_ollama(url, timeout=2))
            path = logger.generate_report()
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("not reachable", text)

    def test_crash_hook_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DebugLogger("vision-image-optimizer", "0.1.0",
                                 log_dir=tmp)
            previous = sys.excepthook
            sys.excepthook = lambda *args: None
            try:
                logger.install_crash_handler()
                try:
                    raise ValueError("boom-test-value")
                except ValueError:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    sys.excepthook(exc_type, exc_value, exc_tb)
                logger.uninstall_crash_handler()
            finally:
                sys.excepthook = previous
            reports = glob.glob(os.path.join(
                tmp, "debug-report-vision-image-optimizer-*.txt"))
            self.assertEqual(len(reports), 1)
            with open(reports[0], encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("boom-test-value", text)
            self.assertIn("UNHANDLED EXCEPTION", text)


if __name__ == "__main__":
    unittest.main()
