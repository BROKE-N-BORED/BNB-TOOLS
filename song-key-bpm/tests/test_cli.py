"""CLI tests: help, version, analyze, export, exit codes.

The CLI runs in a subprocess (the venv python, `python -m
songkey`) so exit codes and stdout/stderr are checked the way a
user sees them. XDG_DATA_HOME points at a temp dir so the debug
log never touches the real home.
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
EXPECTED_KEYS = {
    "path", "file", "bpm", "bpm_confidence", "tempo_bpm",
    "key", "key_confidence", "key_score", "key_margin",
    "key_runner_up", "duration", "error",
}


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.data_home = os.path.join(cls.dir, "data")
        cls.fixtures = os.path.join(cls.dir, "fixtures")
        helpers.make_fixture_dir(
            cls.fixtures, ("click120", "aminor"))
        cls.click = os.path.join(cls.fixtures, "click120.wav")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, argv, cwd=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = TREE
        env["XDG_DATA_HOME"] = self.data_home
        return subprocess.run(
            [sys.executable, "-m", "songkey"] + argv,
            capture_output=True, text=True, cwd=cwd or self.dir,
            env=env)

    def test_help_exits_zero(self):
        result = self._run(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("analyze", result.stdout)
        self.assertIn("export", result.stdout)

    def test_analyze_help_exits_zero(self):
        result = self._run(["analyze", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("--json", result.stdout)
        self.assertIn("--out", result.stdout)

    def test_version_prints_0_1_0(self):
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_analyze_file_to_json(self):
        out = os.path.join(self.dir, "one.json")
        result = self._run(["analyze", self.click, "--out", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]), EXPECTED_KEYS)
        self.assertAlmostEqual(data[0]["bpm"], 120, delta=1)
        self.assertIsNone(data[0]["error"])

    def test_analyze_json_flag_prints_json(self):
        result = self._run(["analyze", self.click, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]), EXPECTED_KEYS)

    def test_analyze_folder_finds_the_wavs(self):
        out = os.path.join(self.dir, "folder.json")
        result = self._run(["analyze", self.fixtures, "--out", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)
        names = sorted(item["file"] for item in data)
        self.assertEqual(names, ["aminor.wav", "click120.wav"])

    def test_export_converts_json_to_csv(self):
        src = os.path.join(self.dir, "src.json")
        self._run(["analyze", self.fixtures, "--out", src])
        csv_path = os.path.join(self.dir, "table.csv")
        result = self._run(["export", src, "--format", "csv",
                            "--out", csv_path])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(csv_path, encoding="utf-8") as fh:
            lines = fh.read().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("file,bpm,"))
        self.assertIn("click120.wav", lines[1] + lines[2])

    def test_export_both_writes_two_files(self):
        src = os.path.join(self.dir, "src2.json")
        self._run(["analyze", self.click, "--out", src])
        base = os.path.join(self.dir, "both")
        result = self._run(["export", src, "--format", "both",
                            "--out", base])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(base + ".csv"))
        self.assertTrue(os.path.exists(base + ".json"))

    def test_bad_usage_exits_2(self):
        result = self._run(["analyze"])
        self.assertEqual(result.returncode, 2)
        result = self._run(["export", "x.json", "--format", "both"])
        self.assertEqual(result.returncode, 2)
        result = self._run(["frobnicate"])
        self.assertEqual(result.returncode, 2)

    def test_missing_file_warns_and_continues(self):
        missing = os.path.join(self.dir, "gone.wav")
        result = self._run(["analyze", missing, self.click])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gone.wav", result.stderr)
        self.assertIn("click120.wav", result.stdout)

    def test_nothing_analyzed_exits_1(self):
        missing = os.path.join(self.dir, "gone.wav")
        result = self._run(["analyze", missing])
        self.assertEqual(result.returncode, 1)
        self.assertIn("gone.wav", result.stderr)


class MissingDependencyTests(unittest.TestCase):
    """A missing audio library is plain words, never a traceback.

    Runs the CLI under the system python3 from PATH, which has no
    aubio (the app's own venv does). Skipped when that python can
    import aubio, since the scenario does not apply there.
    Regression test for the parent-found defect at ship time:
    the CLI import raised a bare ModuleNotFoundError traceback.
    """

    def test_missing_aubio_is_plain_words_not_traceback(self):
        import shutil
        system_python = shutil.which("python3")
        self.assertIsNotNone(system_python, "no python3 on PATH")
        probe = subprocess.run(
            [system_python, "-c", "import aubio"],
            capture_output=True, text=True)
        if probe.returncode == 0:
            self.skipTest("system python3 has aubio installed")
        env = dict(os.environ)
        env["PYTHONPATH"] = TREE
        result = subprocess.run(
            [system_python, "-m", "songkey", "--help"],
            capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("needs aubio", result.stderr)
        self.assertIn("Install Song Key BPM", result.stderr)


if __name__ == "__main__":
    unittest.main()
