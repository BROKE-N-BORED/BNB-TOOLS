"""Full-chain test: wrapper scripts end to end, no Qt needed.

The wrappers run through bash (not direct exec: direct exec
fails in clone simulations where files land 100644). The venv
python leads PATH so the wrapper's `python3` is the python with
aubio and miniaudio installed. The run happens from a temp
working directory with relative paths, proving the wrappers do
not cd away from the caller.
"""

import csv
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
WRAPPERS = ("song-key-analyze", "song-key-export", "songkey-cli")
NO_QT_MODULES = ("__init__.py", "__main__.py", "analyze.py",
                 "cli.py", "decode.py", "export.py", "key.py",
                 "logsetup.py", "settings.py", "tempo.py")


class ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.data_home = os.path.join(cls.dir, "data")
        cls.fixtures = os.path.join(cls.dir, "fixtures")
        helpers.make_fixture_dir(
            cls.fixtures, ("click120", "aminor", "combo"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _env(self):
        env = dict(os.environ)
        venv_bin = os.path.dirname(sys.executable)
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["XDG_DATA_HOME"] = self.data_home
        return env

    def _bash(self, wrapper, argv):
        return subprocess.run(
            ["bash", os.path.join(TREE, wrapper)] + argv,
            capture_output=True, text=True, cwd=self.dir,
            env=self._env())

    def test_wrappers_answer_help(self):
        for wrapper in WRAPPERS:
            result = self._bash(wrapper, ["--help"])
            self.assertEqual(result.returncode, 0,
                             "%s --help failed: %s"
                             % (wrapper, result.stderr))
            self.assertIn("Song Key BPM", result.stdout)

    def test_wrappers_are_executable(self):
        # The shipped property is the zip's stored mode, which
        # build_zip.py sets from its SCRIPTS table — not the live
        # tree's filesystem bit, which a plain copy (or the clone
        # simulation, all files 100644) drops. Git preserves the
        # bit from the repo; the zip sets it explicitly either way.
        # (Coordinator fix: this test used to assert os.X_OK on the
        # tree and failed the clone simulation for that reason.)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_zip", os.path.join(TREE, "build_zip.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for wrapper in WRAPPERS:
            self.assertIn(wrapper, module.SCRIPTS, wrapper)

    def test_full_chain_wrapper_to_csv(self):
        # Relative paths from the temp working directory.
        analyzed = self._bash("song-key-analyze",
                              ["fixtures", "--out", "results.json"])
        self.assertEqual(analyzed.returncode, 0, analyzed.stderr)
        with open(os.path.join(self.dir, "results.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)
        by_name = {item["file"]: item for item in data}
        self.assertAlmostEqual(by_name["click120.wav"]["bpm"],
                               120, delta=1)
        self.assertEqual(by_name["aminor.wav"]["key"], "A minor")
        self.assertIsNone(by_name["click120.wav"]["key"])

        exported = self._bash("song-key-export",
                              ["results.json", "--format", "csv",
                               "--out", "table.csv"])
        self.assertEqual(exported.returncode, 0, exported.stderr)
        with open(os.path.join(self.dir, "table.csv"),
                  encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0],
                         ["file", "bpm", "bpm_confidence", "key",
                          "key_confidence", "key_runner_up",
                          "duration"])
        self.assertEqual(len(rows), 4)
        names = sorted(row[0] for row in rows[1:])
        self.assertEqual(names, ["aminor.wav", "click120.wav",
                                 "combo.wav"])

    def test_cli_modules_never_import_qt(self):
        # The CLI must work with no Qt installed: no PySide6 (or
        # other Qt binding) import anywhere in the core modules.
        for module in NO_QT_MODULES:
            path = os.path.join(TREE, "songkey", module)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for marker in ("PySide6", "PyQt6", "PyQt5", "PySide2"):
                self.assertNotIn(marker, text, "%s in %s"
                                 % (marker, module))


if __name__ == "__main__":
    unittest.main()
