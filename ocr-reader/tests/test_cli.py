"""CLI tests: help, version, read, clean, exit codes.

The CLI runs in a subprocess (the venv python, `python -m
ocrreader`) so exit codes and stdout/stderr are checked the way
a user sees them. XDG_DATA_HOME points at a temp dir so the
debug log never touches the real home. OCR_TESSERACT points at
a stub so read tests never need the real binary.
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
EXPECTED_KEYS = {"path", "file", "text", "pages", "language",
                 "error"}
CANNED_TEXT = "the quick brown fox\n"


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.data_home = os.path.join(cls.dir, "data")
        cls.empty_dir = os.path.join(cls.dir, "empty")
        os.mkdir(cls.empty_dir)
        cls.stub = helpers.make_fake_tesseract(
            cls.dir, text=CANNED_TEXT)
        cls.image = os.path.join(cls.dir, "page.png")
        with open(cls.image, "wb") as fh:
            fh.write(b"not a real png, the stub never looks")
        cls.image2 = os.path.join(cls.dir, "second.png")
        with open(cls.image2, "wb") as fh:
            fh.write(b"not a real png either")
        cls.messy = os.path.join(cls.dir, "messy.txt")
        with open(cls.messy, "w", encoding="utf-8") as fh:
            fh.write("hello  world .  \n\n\nthe fox\njumps\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, argv, input_text=None, extra_env=None,
             remove_env=()):
        env = dict(os.environ)
        env["PYTHONPATH"] = TREE
        env["XDG_DATA_HOME"] = self.data_home
        env["OCR_TESSERACT"] = self.stub
        for key in remove_env:
            env.pop(key, None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "ocrreader"] + argv,
            capture_output=True, text=True, input=input_text,
            cwd=self.dir, env=env)

    def test_help_exits_zero(self):
        result = self._run(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("read", result.stdout)
        self.assertIn("clean", result.stdout)
        self.assertIn("debug-report", result.stdout)

    def test_read_help_exits_zero(self):
        result = self._run(["read", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("--lang", result.stdout)
        self.assertIn("--json", result.stdout)
        self.assertIn("--out", result.stdout)

    def test_clean_help_exits_zero(self):
        result = self._run(["clean", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("stdin", result.stdout)

    def test_version_prints_0_1_0(self):
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)
        self.assertIn("OCR Reader", result.stdout)

    def test_no_command_prints_help_exit_zero(self):
        # In-process: `python -m ocrreader` with no arguments
        # opens the window, so the bare-CLI help path is only
        # reachable as cli.main([]).
        import io
        from contextlib import redirect_stdout
        from ocrreader.cli import main as cli_main
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli_main([])
        self.assertEqual(code, 0)
        self.assertIn("read", out.getvalue())

    def test_read_json_exact_schema(self):
        result = self._run(["read", self.image, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]), EXPECTED_KEYS)
        self.assertEqual(data[0]["file"], "page.png")
        self.assertEqual(data[0]["text"], CANNED_TEXT)
        self.assertEqual(data[0]["pages"], 1)
        self.assertEqual(data[0]["language"], "eng")
        self.assertIsNone(data[0]["error"])

    def test_read_json_language_flag(self):
        result = self._run(["read", self.image, "--json",
                            "--lang", "fra"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data[0]["language"], "fra")

    def test_read_plain_output(self):
        result = self._run(["read", self.image])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, CANNED_TEXT)

    def test_read_multi_file_marker(self):
        result = self._run(["read", self.image, self.image2])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\n--- second.png ---\n", result.stdout)
        self.assertEqual(result.stdout.count(CANNED_TEXT.strip()),
                         2)

    def test_read_out_writes_file(self):
        out = os.path.join(self.dir, "out.txt")
        result = self._run(["read", self.image, "--out", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wrote", result.stdout)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), CANNED_TEXT)

    def test_read_missing_file_exit_1(self):
        missing = os.path.join(self.dir, "nope.png")
        result = self._run(["read", missing])
        self.assertEqual(result.returncode, 1)
        self.assertIn("Nothing was read.", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_read_no_files_exit_2(self):
        result = self._run(["read"])
        self.assertEqual(result.returncode, 2)

    def test_unknown_command_exit_2(self):
        result = self._run(["frobnicate"])
        self.assertEqual(result.returncode, 2)

    def test_clean_file(self):
        result = self._run(["clean", self.messy])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         "hello world.\n\nthe fox jumps\n")

    def test_clean_stdin(self):
        result = self._run(["clean"], input_text="a  b  \n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "a b\n")

    def test_clean_json(self):
        result = self._run(["clean", self.messy, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data), {"text", "changes"})
        self.assertEqual(data["text"],
                         "hello world.\n\nthe fox jumps")
        self.assertIn("joined 1 wrapped line", data["changes"])

    def test_clean_out_writes_file(self):
        out = os.path.join(self.dir, "cleaned.txt")
        result = self._run(["clean", self.messy, "--out", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(fh.read(),
                             "hello world.\n\nthe fox jumps\n")

    def test_clean_missing_file_exit_1(self):
        missing = os.path.join(self.dir, "nope.txt")
        result = self._run(["clean", missing])
        self.assertEqual(result.returncode, 1)
        self.assertIn("nope.txt", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_debug_report(self):
        result = self._run(["debug-report"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Debug report written to", result.stdout)
        log_dir = os.path.join(self.data_home, "ocr-reader",
                               "logs")
        reports = [name for name in os.listdir(log_dir)
                   if name.startswith("debug-report-")]
        self.assertEqual(len(reports), 1)

    def test_missing_binary_regression(self):
        # PATH scrubbed to an empty dir, OCR_TESSERACT unset:
        # exit 1, no traceback, plain message naming tesseract
        # and the apt install command.
        result = self._run(
            ["read", self.image],
            extra_env={"PATH": self.empty_dir},
            remove_env=("OCR_TESSERACT",))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Tesseract is not installed", result.stderr)
        self.assertIn("sudo apt install tesseract-ocr",
                      result.stderr)


if __name__ == "__main__":
    unittest.main()
