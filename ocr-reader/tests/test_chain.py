"""Full-chain test: wrapper scripts end to end, no Qt needed.

The wrappers run through bash (not direct exec: direct exec
fails in clone simulations where files land 100644). The venv
python leads PATH so the wrapper's `python3` is the python the
tests run under. The run happens from a temp working directory
with relative paths, proving the wrappers do not cd away from
the caller.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPERS = ("ocr-read", "ocr-clean", "ocrreader-cli")
NO_QT_MODULES = ("__init__.py", "__main__.py", "clean.py",
                 "cli.py", "debug_log.py", "engine.py",
                 "logsetup.py")
# Messy on purpose: the stub prints it, clean must fix it.
CANNED_MESSY = ("the quick brown\n"
                "fox jumps  over the lazy\n"
                "dog .  \n"
                "\n"
                "\n")


class ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.data_home = os.path.join(cls.dir, "data")
        cls.stub = helpers.make_fake_tesseract(
            cls.dir, text=CANNED_MESSY)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _env(self):
        env = dict(os.environ)
        venv_bin = os.path.dirname(sys.executable)
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["XDG_DATA_HOME"] = self.data_home
        env["OCR_TESSERACT"] = self.stub
        return env

    def _bash(self, wrapper, argv):
        return subprocess.run(
            ["bash", os.path.join(TREE, wrapper)] + argv,
            capture_output=True, text=True, cwd=self.dir,
            env=self._env())

    def test_wrappers_answer_help(self):
        result = self._bash("ocr-read", ["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--lang", result.stdout)
        result = self._bash("ocr-clean", ["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stdin", result.stdout)
        result = self._bash("ocrreader-cli", ["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("read", result.stdout)
        self.assertIn("clean", result.stdout)
        self.assertIn("debug-report", result.stdout)

    @unittest.skipUnless(helpers.FONT_AVAILABLE,
                         "DejaVuSans is not installed")
    def test_full_chain_read_then_clean(self):
        # Relative paths from the temp working directory.
        helpers.render_text_image(helpers.PROBE_LINES,
                                  os.path.join(self.dir, "page.png"))
        read = self._bash("ocr-read",
                          ["page.png", "--out", "raw.txt"])
        self.assertEqual(read.returncode, 0, read.stderr)
        with open(os.path.join(self.dir, "raw.txt"),
                  encoding="utf-8") as fh:
            raw = fh.read()
        self.assertEqual(raw, CANNED_MESSY)
        cleaned = self._bash("ocr-clean",
                             ["raw.txt", "--out", "clean.txt"])
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        with open(os.path.join(self.dir, "clean.txt"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(
            text, "the quick brown fox jumps over the lazy dog.\n")

    @unittest.skipUnless(helpers.FONT_AVAILABLE,
                         "DejaVuSans is not installed")
    def test_chain_json_through_wrapper(self):
        helpers.render_text_image(helpers.PROBE_LINES,
                                  os.path.join(self.dir, "page.png"))
        result = self._bash("ocr-read", ["page.png", "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]),
                         {"path", "file", "text", "pages",
                          "language", "error"})
        self.assertEqual(data[0]["text"], CANNED_MESSY)
        self.assertIsNone(data[0]["error"])

    def test_cli_modules_never_import_qt(self):
        # The CLI must work with no Qt installed: no PySide6 (or
        # other Qt binding) import anywhere in the core modules.
        for module in NO_QT_MODULES:
            path = os.path.join(TREE, "ocrreader", module)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for marker in ("PySide6", "PyQt6", "PyQt5", "PySide2"):
                self.assertNotIn(marker, text, "%s in %s"
                                 % (marker, module))


if __name__ == "__main__":
    unittest.main()
