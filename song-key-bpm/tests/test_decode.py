"""Decode tests: WAV, resample, MP3, and plain-language errors."""

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
from songkey import decode  # noqa: E402
from songkey.decode import DecodeError, decode_audio  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_wav_decode_round_trip(self):
        path = helpers.make_fixture("click120", self.dir)
        samples, duration = decode_audio(path)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(duration, 10.0, places=1)
        self.assertAlmostEqual(len(samples), 10 * 44100, delta=100)
        self.assertLessEqual(np.max(np.abs(samples)), 1.0)
        self.assertGreater(np.max(np.abs(samples)), 0.1)

    def test_resample_22050_to_44100(self):
        path = helpers.make_fixture("click120", self.dir, sr=22050)
        samples, duration = decode_audio(path)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(duration, 10.0, places=1)
        self.assertAlmostEqual(len(samples), 10 * 44100, delta=100)

    def test_resample_48000_to_44100(self):
        path = helpers.make_fixture("click120", self.dir, sr=48000)
        samples, duration = decode_audio(path)
        self.assertAlmostEqual(duration, 10.0, places=1)
        self.assertAlmostEqual(len(samples), 10 * 44100, delta=100)

    def test_unreadable_file_error_names_the_file(self):
        path = os.path.join(self.dir, "garbage.wav")
        with open(path, "wb") as fh:
            fh.write(b"this is not audio at all" * 40)
        with self.assertRaises(DecodeError) as caught:
            decode_audio(path)
        message = str(caught.exception)
        self.assertIn("garbage.wav", message)
        self.assertNotIn("Traceback", message)

    def test_missing_file_error_names_the_file(self):
        path = os.path.join(self.dir, "no-such-file.wav")
        with self.assertRaises(DecodeError) as caught:
            decode_audio(path)
        message = str(caught.exception)
        self.assertIn("no-such-file.wav", message)
        self.assertNotIn("Traceback", message)

    def test_wave_fallback_without_miniaudio(self):
        path = helpers.make_fixture("click120", self.dir)
        old = decode.miniaudio
        decode.miniaudio = None
        try:
            samples, duration = decode_audio(path)
        finally:
            decode.miniaudio = old
        self.assertAlmostEqual(duration, 10.0, places=1)
        self.assertGreater(len(samples), 0)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
    def test_mp3_decode(self):
        wav_path = helpers.make_fixture("click147", self.dir)
        mp3_path = os.path.join(self.dir, "click147.mp3")
        helpers.make_mp3(wav_path, mp3_path)
        samples, duration = decode_audio(mp3_path)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(duration, 10.0, places=1)
        self.assertGreater(np.max(np.abs(samples)), 0.1)


if __name__ == "__main__":
    unittest.main()
