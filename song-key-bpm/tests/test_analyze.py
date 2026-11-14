"""analyze_file tests: the result schema end to end."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402
from songkey.analyze import RESULT_KEYS, analyze_file  # noqa: E402

EXPECTED_KEYS = {
    "path", "file", "bpm", "bpm_confidence", "tempo_bpm",
    "key", "key_confidence", "key_score", "key_margin",
    "key_runner_up", "duration", "error",
}


class AnalyzeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.combo = helpers.make_fixture("combo", cls.dir)
        cls.click = helpers.make_fixture("click120", cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_schema_keys_exactly_as_designed(self):
        self.assertEqual(set(RESULT_KEYS), EXPECTED_KEYS)
        result = analyze_file(self.combo)
        self.assertEqual(set(result), EXPECTED_KEYS)

    def test_combo_success(self):
        result = analyze_file(self.combo)
        self.assertIsNone(result["error"])
        self.assertEqual(result["file"], "combo.wav")
        self.assertTrue(result["path"].endswith("combo.wav"))
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], 120, delta=1)
        self.assertIn(result["bpm_confidence"], ("high", "low"))
        self.assertIn(result["key"], ("A minor", "C major"))
        self.assertIn(result["key_confidence"], ("high", "low"))
        self.assertIsNotNone(result["key_score"])
        self.assertIsNotNone(result["key_margin"])
        self.assertAlmostEqual(result["duration"], 8.0, places=1)

    def test_click_track_key_unknown_bpm_known(self):
        result = analyze_file(self.click)
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["bpm"])
        self.assertIsNone(result["key"])
        self.assertEqual(result["key_confidence"], "unknown")

    def test_corrupt_file_returns_plain_error(self):
        path = os.path.join(self.dir, "broken.wav")
        with open(path, "wb") as fh:
            fh.write(b"not audio, just bytes" * 50)
        result = analyze_file(path)
        self.assertIsNotNone(result["error"])
        self.assertNotIn("Traceback", result["error"])
        self.assertIn("broken.wav", result["error"])
        self.assertIsNone(result["bpm"])
        self.assertIsNone(result["key"])
        self.assertIsNone(result["duration"])
        self.assertEqual(result["bpm_confidence"], "unknown")
        self.assertEqual(result["key_confidence"], "unknown")

    def test_missing_file_returns_plain_error(self):
        path = os.path.join(self.dir, "missing.wav")
        result = analyze_file(path)
        self.assertIsNotNone(result["error"])
        self.assertNotIn("Traceback", result["error"])
        self.assertIn("missing.wav", result["error"])
        self.assertIsNone(result["bpm"])


if __name__ == "__main__":
    unittest.main()
