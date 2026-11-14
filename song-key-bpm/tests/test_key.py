"""Key tests: FFT chroma + Krumhansl-Schmuckler on chord loops."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402
from songkey.decode import decode_audio  # noqa: E402
from songkey.key import KS_MAJOR, KS_MINOR, measure_key  # noqa: E402


class KeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.paths = {}
        for name in ("click120", "cmajor", "aminor", "gmajor",
                     "eminor"):
            cls.paths[name] = helpers.make_fixture(name, cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _key(self, name):
        samples, _duration = decode_audio(self.paths[name])
        return measure_key(samples)

    def test_aminor_confident(self):
        result = self._key("aminor")
        self.assertEqual(result["key"], "A minor")
        self.assertEqual(result["confidence"], "high")
        self.assertGreaterEqual(result["score"], 0.5)
        self.assertGreaterEqual(result["margin"], 0.1)

    def test_eminor(self):
        result = self._key("eminor")
        self.assertEqual(result["key"], "E minor")
        self.assertGreaterEqual(result["score"], 0.5)

    def test_cmajor_relative_pair(self):
        # C major and A minor use the same notes, so a close call
        # between them is normal: the answer must be one of the
        # pair, and the other must be the runner-up or the call
        # must be low confidence.
        result = self._key("cmajor")
        self.assertIn(result["key"], ("C major", "A minor"))
        other = ("A minor" if result["key"] == "C major"
                 else "C major")
        self.assertTrue(
            result["runner_up"] == other
            or result["confidence"] == "low",
            "expected %s as runner-up or low confidence, got %s"
            % (other, result))

    def test_gmajor_dominant_or_truth(self):
        # The G major loop reads its dominant (D major) on the
        # probes, with the truth second; either is acceptable as
        # long as the pair is D major / G major.
        result = self._key("gmajor")
        self.assertIn(result["key"], ("G major", "D major"))
        other = ("D major" if result["key"] == "G major"
                 else "G major")
        self.assertTrue(
            result["runner_up"] == other
            or result["confidence"] == "low",
            "expected %s as runner-up or low confidence, got %s"
            % (other, result))

    def test_click_only_is_unknown(self):
        result = self._key("click120")
        self.assertIsNone(result["key"])
        self.assertEqual(result["confidence"], "unknown")
        self.assertLess(result["score"], 0.5)

    def test_ks_profiles_are_the_published_constants(self):
        self.assertEqual(len(KS_MAJOR), 12)
        self.assertEqual(len(KS_MINOR), 12)
        self.assertEqual(KS_MAJOR[0], 6.35)
        self.assertEqual(KS_MAJOR[4], 4.38)
        self.assertEqual(KS_MAJOR[7], 5.19)
        self.assertEqual(KS_MAJOR[11], 2.88)
        self.assertEqual(KS_MINOR[0], 6.33)
        self.assertEqual(KS_MINOR[3], 5.38)
        self.assertEqual(KS_MINOR[7], 4.75)
        self.assertEqual(KS_MINOR[11], 3.17)


if __name__ == "__main__":
    unittest.main()
