"""Live tests: the REAL tesseract binary.

The whole class skips when tesseract is not installed, when
DejaVuSans is missing, and unless OCR_RUN_LIVE=1 is set: real
tesseract runs very slowly on this sandbox's shared, throttled
CPU (one call took 105s during a loaded run), so the live tests
stay out of the default suite and run on demand with
`OCR_RUN_LIVE=1 run_tests.sh`. Measured in this sandbox on
2026-11-14: the paragraph fixture reads at 100% (44/44 words)
as a PNG and 100% as a one-page PDF; the tests assert >= 90%
to leave margin below the measured value.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402
from ocrreader.engine import read_file  # noqa: E402


def _without_page_markers(text):
    """Drop the '--- page N ---' lines before scoring."""
    return "\n".join(line for line in text.splitlines()
                     if not line.startswith("--- page "))


@unittest.skipUnless(shutil.which("tesseract"),
                     "tesseract is not installed")
@unittest.skipUnless(helpers.FONT_AVAILABLE,
                     "DejaVuSans is not installed")
@unittest.skipUnless(os.environ.get("OCR_RUN_LIVE") == "1",
                     "live tests run only with OCR_RUN_LIVE=1")
class LiveTests(unittest.TestCase):
    # The live tests measure accuracy, not the timeout (the
    # stub tests cover that). They pass a long timeout because
    # real tesseract runs very slowly on this sandbox's shared,
    # throttled CPU: one call took 105s during a loaded run,
    # near the 120s production default. On Joshua's PC a small
    # image takes seconds.
    TIMEOUT = 300
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_paragraph_accuracy(self):
        path = helpers.render_text_image(
            helpers.PARAGRAPH_LINES,
            os.path.join(self.dir, "paragraph.png"))
        result = read_file(path, timeout=self.TIMEOUT)
        self.assertIsNone(result["error"])
        self.assertEqual(result["pages"], 1)
        expected = "\n".join(helpers.PARAGRAPH_LINES)
        accuracy = helpers.word_accuracy(expected, result["text"])
        self.assertGreaterEqual(accuracy, 0.90,
                                "accuracy %.2f on:\n%s"
                                % (accuracy, result["text"]))

    def test_two_line_probe(self):
        path = helpers.render_text_image(
            helpers.PROBE_LINES,
            os.path.join(self.dir, "probe.png"))
        result = read_file(path, timeout=self.TIMEOUT)
        self.assertIsNone(result["error"])
        text = result["text"].lower()
        self.assertIn("quick brown fox", text)
        self.assertIn("12345", text)

    @unittest.skipUnless(shutil.which("pdftoppm"),
                         "pdftoppm is not installed")
    def test_live_pdf_accuracy(self):
        path = helpers.render_paragraph_pdf(
            os.path.join(self.dir, "paragraph.pdf"))
        result = read_file(path, timeout=self.TIMEOUT)
        self.assertIsNone(result["error"])
        self.assertEqual(result["pages"], 1)
        expected = "\n".join(helpers.PARAGRAPH_LINES)
        scored = _without_page_markers(result["text"])
        accuracy = helpers.word_accuracy(expected, scored)
        self.assertGreaterEqual(accuracy, 0.90,
                                "accuracy %.2f on:\n%s"
                                % (accuracy, result["text"]))


if __name__ == "__main__":
    unittest.main()
