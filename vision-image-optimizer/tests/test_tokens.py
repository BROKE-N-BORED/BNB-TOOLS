"""Token math, resize, crop, sizes, and measurements lines."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import make_image  # noqa: E402
from optimizer import tokens  # noqa: E402


class TokenMathTests(unittest.TestCase):
    def test_1080p_is_2040(self):
        self.assertEqual(tokens.vision_tokens(1920, 1080), 2040)

    def test_512x288_is_144(self):
        self.assertEqual(tokens.vision_tokens(512, 288), 144)

    def test_1x1_is_1(self):
        self.assertEqual(tokens.vision_tokens(1, 1), 1)

    def test_odd_sizes_round_up(self):
        self.assertEqual(tokens.vision_tokens(100, 100), 16)
        self.assertEqual(tokens.vision_tokens(33, 33), 4)
        self.assertEqual(tokens.vision_tokens(32, 32), 1)
        self.assertEqual(tokens.vision_tokens(31, 31), 1)

    def test_14x_win(self):
        before = tokens.vision_tokens(1920, 1080)
        after = tokens.vision_tokens(512, 288)
        self.assertAlmostEqual(before / after, 14.17, places=1)

    def test_invalid_size_rejected(self):
        with self.assertRaises(ValueError):
            tokens.vision_tokens(0, 100)


class TargetSizeTests(unittest.TestCase):
    def test_resize_keeps_aspect(self):
        self.assertEqual(tokens.target_size(1920, 1080, 512),
                         (512, 288))
        self.assertEqual(tokens.target_size(1000, 500, 500),
                         (500, 250))

    def test_never_upscales(self):
        self.assertEqual(tokens.target_size(800, 600, 1024),
                         (800, 600))
        self.assertEqual(tokens.target_size(800, 600, None),
                         (800, 600))

    def test_target_below_one_rejected(self):
        with self.assertRaises(ValueError):
            tokens.target_size(800, 600, 0)


class ClampCropTests(unittest.TestCase):
    def test_crop_inside(self):
        self.assertEqual(tokens.clamp_crop((10, 20, 100, 50), 1920,
                                           1080), (10, 20, 100, 50))

    def test_crop_partly_outside_is_clamped(self):
        self.assertEqual(tokens.clamp_crop((1900, 1000, 200, 200),
                                           1920, 1080),
                         (1900, 1000, 20, 80))

    def test_crop_starting_outside_loses_the_outside_part(self):
        # Intersection math: a box starting left of / above the
        # picture loses that part of its width / height; it does
        # not slide to (0, 0) keeping its size.
        self.assertEqual(tokens.clamp_crop((-50, -20, 100, 100),
                                           1920, 1080),
                         (0, 0, 50, 80))
        self.assertEqual(tokens.clamp_crop((-10, 100, 50, 50),
                                           1920, 1080),
                         (0, 100, 40, 50))

    def test_crop_fully_outside_is_none(self):
        self.assertIsNone(tokens.clamp_crop((5000, 5000, 10, 10),
                                            1920, 1080))
        self.assertIsNone(tokens.clamp_crop((-100, -100, 50, 50),
                                            1920, 1080))

    def test_none_crop_is_none(self):
        self.assertIsNone(tokens.clamp_crop(None, 1920, 1080))


class HumanSizeTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(tokens.human_size(0), "0 B")
        self.assertEqual(tokens.human_size(512), "512 B")
        self.assertEqual(tokens.human_size(1023), "1023 B")

    def test_kilobytes(self):
        self.assertEqual(tokens.human_size(1024), "1.0 KB")
        self.assertEqual(tokens.human_size(1536), "1.5 KB")
        self.assertEqual(tokens.human_size(100000), "97.7 KB")

    def test_megabytes_and_up(self):
        self.assertEqual(tokens.human_size(1048576), "1.0 MB")
        self.assertEqual(tokens.human_size(1073741824), "1.0 GB")


class MeasurementsTests(unittest.TestCase):
    def test_describe_measurements_keys(self):
        measure = tokens.describe_measurements(0.5, 1.25, 2040, 144,
                                               100000, 20000)
        self.assertEqual(measure, {
            "fast_seconds": 0.5,
            "smart_seconds": 1.25,
            "tokens_before": 2040,
            "tokens_after": 144,
            "bytes_before": 100000,
            "bytes_after": 20000,
        })

    def test_format_fast_only(self):
        measure = tokens.describe_measurements(0.5, None, 2040, 144,
                                               100000, 20000)
        self.assertEqual(
            tokens.format_measurements(measure),
            "Fast look: 0.50 s  Tokens: 2040 to 144  "
            "Size: 97.7 KB to 19.5 KB")

    def test_format_both_looks(self):
        measure = tokens.describe_measurements(0.5, 1.25, 2040, 144,
                                               100000, 20000)
        line = tokens.format_measurements(measure)
        self.assertIn("Fast look: 0.50 s", line)
        self.assertIn("Careful look: 1.25 s", line)
        self.assertIn("Tokens: 2040 to 144", line)
        self.assertIn("Size: 97.7 KB to 19.5 KB", line)

    def test_format_no_looks(self):
        measure = tokens.describe_measurements(None, None, 144, 144,
                                               20000, 20000)
        self.assertEqual(
            tokens.format_measurements(measure),
            "Tokens: 144 to 144  Size: 19.5 KB to 19.5 KB")


class ImageInfoTests(unittest.TestCase):
    def test_image_info_reads_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              640, 480)
            info = tokens.image_info(path)
            self.assertEqual(info["width"], 640)
            self.assertEqual(info["height"], 480)
            self.assertEqual(info["bytes"],
                             os.path.getsize(path))


class ConstantsTests(unittest.TestCase):
    def test_token_px(self):
        self.assertEqual(tokens.TOKEN_PX, 32)

    def test_supported_extensions(self):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            self.assertIn(ext, tokens.SUPPORTED_EXTENSIONS)
        self.assertNotIn(".txt", tokens.SUPPORTED_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
