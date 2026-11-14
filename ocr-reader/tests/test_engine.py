"""Engine tests: stub-based, no real tesseract needed.

OCR_TESSERACT points at a stub script that prints canned text,
so extraction, errors, timeouts and the PDF path are all tested
without the real binary. The real binary is exercised only in
test_live.py.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402
from ocrreader.engine import (OCRError, PDFTOPPM_MISSING,  # noqa: E402
                              TESSERACT_MISSING, find_tesseract,
                              ocr_image, read_file, read_files)

EXPECTED_KEYS = {"path", "file", "text", "pages", "language",
                 "error"}


class EngineStubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.empty_dir = os.path.join(self.dir, "empty")
        os.mkdir(self.empty_dir)
        self.image = os.path.join(self.dir, "page.png")
        with open(self.image, "wb") as fh:
            fh.write(b"not a real png, the stub never looks")
        self.image2 = os.path.join(self.dir, "second.png")
        with open(self.image2, "wb") as fh:
            fh.write(b"not a real png either")
        self.stub = helpers.make_fake_tesseract(
            self.dir, text="the quick brown fox\n")
        self._patch = mock.patch.dict(
            os.environ, {"OCR_TESSERACT": self.stub})
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def _no_binary_env(self):
        """Env with no tesseract anywhere: empty PATH, no override."""
        env = dict(os.environ)
        env.pop("OCR_TESSERACT", None)
        env.pop("OCR_PDFTOPPM", None)
        env["PATH"] = self.empty_dir
        return mock.patch.dict(os.environ, env, clear=True)

    def test_stub_extracts_canned_text(self):
        self.assertEqual(ocr_image(self.image),
                         "the quick brown fox\n")

    def test_stderr_never_mixes_into_text(self):
        stub = helpers.make_fake_tesseract(
            self.dir, text="clean text\n",
            stderr_text="Warning: something noisy")
        with mock.patch.dict(os.environ, {"OCR_TESSERACT": stub}):
            text = ocr_image(self.image)
        self.assertEqual(text, "clean text\n")
        self.assertNotIn("noisy", text)

    def test_read_file_schema(self):
        result = read_file(self.image)
        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["path"], self.image)
        self.assertEqual(result["file"], "page.png")
        self.assertEqual(result["text"], "the quick brown fox\n")
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["language"], "eng")
        self.assertIsNone(result["error"])

    def test_read_file_language_is_reported(self):
        result = read_file(self.image, lang="fra")
        self.assertEqual(result["language"], "fra")

    def test_read_files_multi(self):
        results = read_files([self.image, self.image2])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["file"], "page.png")
        self.assertEqual(results[1]["file"], "second.png")
        self.assertTrue(all(item["error"] is None
                            for item in results))

    def test_missing_binary_raises_plain_message(self):
        with self._no_binary_env():
            with self.assertRaises(OCRError) as caught:
                find_tesseract()
        self.assertEqual(str(caught.exception), TESSERACT_MISSING)

    def test_missing_binary_read_file_reports_error(self):
        with self._no_binary_env():
            result = read_file(self.image)
        self.assertEqual(result["error"], TESSERACT_MISSING)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["pages"], 0)

    def test_env_override_pointing_nowhere_is_missing(self):
        with mock.patch.dict(
                os.environ,
                {"OCR_TESSERACT": "/nonexistent/tesseract"}):
            with self.assertRaises(OCRError) as caught:
                find_tesseract()
        self.assertEqual(str(caught.exception), TESSERACT_MISSING)

    def test_timeout_names_the_file(self):
        stub = helpers.make_fake_tesseract(self.dir, sleep_seconds=5)
        with mock.patch.dict(os.environ, {"OCR_TESSERACT": stub}):
            with self.assertRaises(OCRError) as caught:
                ocr_image(self.image, timeout=1)
        message = str(caught.exception)
        self.assertIn("Timed out", message)
        self.assertIn("page.png", message)

    def test_missing_input_file(self):
        missing = os.path.join(self.dir, "nope.png")
        result = read_file(missing)
        self.assertIsNotNone(result["error"])
        self.assertIn("nope.png", result["error"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["pages"], 0)

    def test_directory_input_is_an_error(self):
        result = read_file(self.dir)
        self.assertIsNotNone(result["error"])
        self.assertIn(self.dir, result["error"])

    def test_bad_language_surfaces_tesseract_stderr(self):
        stub = helpers.make_fake_tesseract(
            self.dir, fail_langs={
                "xx": "Failed loading language 'xx'"})
        with mock.patch.dict(os.environ, {"OCR_TESSERACT": stub}):
            result = read_file(self.image, lang="xx")
        self.assertEqual(result["error"],
                         "Failed loading language 'xx'")

    def test_nonzero_exit_without_stderr(self):
        stub = helpers.make_fake_tesseract(self.dir, exit_code=1)
        with mock.patch.dict(os.environ, {"OCR_TESSERACT": stub}):
            result = read_file(self.image)
        self.assertIn("tesseract failed", result["error"])
        self.assertIn("page.png", result["error"])


class EnginePdfStubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.empty_dir = os.path.join(self.dir, "empty")
        os.mkdir(self.empty_dir)
        self.pdf = os.path.join(self.dir, "doc.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(b"not a real pdf, the stubs never look")
        self.tess_stub = helpers.make_fake_tesseract(
            self.dir, text="page text\n")
        self.ppm_stub = helpers.make_fake_pdftoppm(self.dir, pages=3)
        self._patch = mock.patch.dict(os.environ, {
            "OCR_TESSERACT": self.tess_stub,
            "OCR_PDFTOPPM": self.ppm_stub})
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_pdf_path_stubbed(self):
        result = read_file(self.pdf)
        self.assertIsNone(result["error"])
        self.assertEqual(result["pages"], 3)
        self.assertIn("--- page 1 ---", result["text"])
        self.assertIn("--- page 2 ---", result["text"])
        self.assertIn("--- page 3 ---", result["text"])
        self.assertEqual(result["text"].count("page text"), 3)

    def test_pdf_missing_pdftoppm(self):
        env = dict(os.environ)
        env.pop("OCR_PDFTOPPM", None)
        env["PATH"] = self.empty_dir
        with mock.patch.dict(os.environ, env, clear=True):
            result = read_file(self.pdf)
        self.assertEqual(result["error"], PDFTOPPM_MISSING)

    def test_pdf_with_no_pages(self):
        ppm_stub = helpers.make_fake_pdftoppm(self.dir, pages=0)
        with mock.patch.dict(os.environ,
                             {"OCR_PDFTOPPM": ppm_stub}):
            result = read_file(self.pdf)
        self.assertIn("No pages found", result["error"])
        self.assertIn("doc.pdf", result["error"])


if __name__ == "__main__":
    unittest.main()
