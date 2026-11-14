"""Tempo tests: onset-interval BPM on known click fixtures."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import helpers  # noqa: E402
from songkey.decode import decode_audio  # noqa: E402
from songkey.tempo import measure_tempo  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class TempoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.paths = {}
        for name in ("click120", "click147", "cmajor", "combo"):
            cls.paths[name] = helpers.make_fixture(name, cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _tempo(self, name):
        samples, _duration = decode_audio(self.paths[name])
        return measure_tempo(samples)

    def test_click120(self):
        result = self._tempo("click120")
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], 120, delta=1)
        self.assertEqual(result["confidence"], "high")

    def test_click147(self):
        result = self._tempo("click147")
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], 147, delta=1.5)

    def test_combo_chords_plus_click(self):
        result = self._tempo("combo")
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], 120, delta=1)

    def test_chord_only_is_unknown(self):
        result = self._tempo("cmajor")
        self.assertIsNone(result["bpm"])
        self.assertEqual(result["confidence"], "unknown")

    def test_cross_check_recorded(self):
        result = self._tempo("click120")
        self.assertIsNotNone(result["tempo_bpm"])
        self.assertAlmostEqual(result["tempo_bpm"], 120, delta=10)
        self.assertGreaterEqual(result["onsets"], 10)
        self.assertGreaterEqual(result["intervals"], 8)

    def test_silence_is_unknown(self):
        samples = np.zeros(44100 * 5, dtype=np.float32)
        result = measure_tempo(samples)
        self.assertIsNone(result["bpm"])
        self.assertEqual(result["confidence"], "unknown")

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
    def test_mp3_click147(self):
        mp3_path = os.path.join(self.dir, "click147.mp3")
        helpers.make_mp3(self.paths["click147"], mp3_path)
        samples, _duration = decode_audio(mp3_path)
        result = measure_tempo(samples)
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], 147, delta=1.5)


if __name__ == "__main__":
    unittest.main()
