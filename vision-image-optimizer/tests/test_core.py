"""Token math, resize, quality, crop, and never-overwrite-source."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import make_image  # noqa: E402
from optimizer import core  # noqa: E402


class TokenMathTests(unittest.TestCase):
    def test_1080p_is_2040(self):
        self.assertEqual(core.vision_tokens(1920, 1080), 2040)

    def test_512x288_is_144(self):
        self.assertEqual(core.vision_tokens(512, 288), 144)

    def test_1x1_is_1(self):
        self.assertEqual(core.vision_tokens(1, 1), 1)

    def test_odd_sizes_round_up(self):
        self.assertEqual(core.vision_tokens(100, 100), 16)
        self.assertEqual(core.vision_tokens(33, 33), 4)
        self.assertEqual(core.vision_tokens(32, 32), 1)
        self.assertEqual(core.vision_tokens(31, 31), 1)

    def test_14x_win(self):
        before = core.vision_tokens(1920, 1080)
        after = core.vision_tokens(512, 288)
        self.assertAlmostEqual(before / after, 14.17, places=1)

    def test_invalid_size_rejected(self):
        with self.assertRaises(ValueError):
            core.vision_tokens(0, 100)


class ResizeTests(unittest.TestCase):
    def test_resize_keeps_aspect(self):
        self.assertEqual(core.target_size(1920, 1080, 512),
                         (512, 288))
        self.assertEqual(core.target_size(1000, 500, 500),
                         (500, 250))

    def test_never_upscales(self):
        self.assertEqual(core.target_size(800, 600, 1024),
                         (800, 600))
        self.assertEqual(core.target_size(800, 600, None),
                         (800, 600))

    def test_resize_result_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "big.png"))
            with open(path, "rb") as fh:
                data = fh.read()
            result = core.optimize_bytes(
                data, {"width": 512, "quality": 85, "format": "JPEG",
                       "crop": None})
            self.assertEqual((result["width"], result["height"]),
                             (512, 288))
            self.assertEqual(result["tokens_before"], 2040)
            self.assertEqual(result["tokens_after"], 144)
            # The shrunken JPEG is smaller than the full-size JPEG
            # of the same picture at the same quality. (A flat PNG
            # source can be smaller than either JPEG, so the honest
            # comparison is JPEG to JPEG.)
            full = core.optimize_bytes(
                data, {"width": None, "quality": 85, "format": "JPEG",
                       "crop": None})
            self.assertLess(result["bytes_after"],
                            full["bytes_after"])


class QualityTests(unittest.TestCase):
    def test_quality_changes_file_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "noise.png"),
                              640, 480, noise=True)
            with open(path, "rb") as fh:
                data = fh.read()
            low = core.optimize_bytes(
                data, {"width": None, "quality": 60, "format": "JPEG",
                       "crop": None})
            high = core.optimize_bytes(
                data, {"width": None, "quality": 95, "format": "JPEG",
                       "crop": None})
            self.assertLess(low["bytes_after"], high["bytes_after"])

    def test_quality_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              100, 100)
            with open(path, "rb") as fh:
                data = fh.read()
            result = core.optimize_bytes(
                data, {"width": None, "quality": 500,
                       "format": "JPEG", "crop": None})
            self.assertGreater(result["bytes_after"], 0)


class CropTests(unittest.TestCase):
    def test_crop_inside(self):
        self.assertEqual(core.clamp_crop((10, 20, 100, 50), 1920,
                                         1080), (10, 20, 100, 50))

    def test_crop_partly_outside_is_clamped(self):
        self.assertEqual(core.clamp_crop((1900, 1000, 200, 200),
                                         1920, 1080),
                         (1900, 1000, 20, 80))

    def test_crop_fully_outside_is_none(self):
        self.assertIsNone(core.clamp_crop((5000, 5000, 10, 10),
                                          1920, 1080))
        self.assertIsNone(core.clamp_crop((-100, -100, 50, 50),
                                          1920, 1080))

    def test_crop_never_crashes_optimize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              200, 150)
            with open(path, "rb") as fh:
                data = fh.read()
            result = core.optimize_bytes(
                data, {"width": None, "quality": 85, "format": "JPEG",
                       "crop": (5000, 5000, 10, 10)})
            self.assertEqual((result["width"], result["height"]),
                             (200, 150))

    def test_crop_changes_output_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              400, 300)
            with open(path, "rb") as fh:
                data = fh.read()
            result = core.optimize_bytes(
                data, {"width": None, "quality": 85, "format": "JPEG",
                       "crop": (0, 0, 200, 150)})
            self.assertEqual((result["width"], result["height"]),
                             (200, 150))
            self.assertEqual(result["tokens_after"],
                             core.vision_tokens(200, 150))


class NeverOverwriteTests(unittest.TestCase):
    def test_output_goes_to_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "shot.png"))
            dest = core.output_path(path, None, 512, "JPEG")
            self.assertEqual(os.path.dirname(dest),
                             os.path.join(tmp, "optimized"))
            self.assertNotEqual(os.path.abspath(dest),
                                os.path.abspath(path))

    def test_output_never_equals_source(self):
        # The output name always carries a size suffix, so it can
        # never be the source name — checked across the awkward
        # cases (a source already carrying a suffix, both formats,
        # original width).
        with tempfile.TemporaryDirectory() as tmp:
            cases = (("shot.png", 512, "JPEG"),
                     ("shot.jpg", 512, "JPEG"),
                     ("shot-512w.jpg", 512, "JPEG"),
                     ("shot.png", None, "PNG"),
                     ("shot-optimized.jpg", None, "JPEG"),
                     ("shot.png", 512, "PNG"))
            for name, width, fmt in cases:
                path = os.path.join(tmp, name)
                with open(path, "wb") as fh:
                    fh.write(b"original")
                dest = core.output_path(path, tmp, width, fmt)
                self.assertNotEqual(os.path.abspath(dest),
                                    os.path.abspath(path),
                                    name)

    def test_write_never_touches_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "shot.png"))
            with open(path, "rb") as fh:
                before = fh.read()
            dest, _ = core.write_optimized(
                path, None,
                {"width": 512, "quality": 85, "format": "JPEG",
                 "crop": None})
            with open(path, "rb") as fh:
                after = fh.read()
            self.assertEqual(before, after)
            self.assertTrue(os.path.exists(dest))
            self.assertNotEqual(os.path.abspath(dest),
                                os.path.abspath(path))


class FormatTests(unittest.TestCase):
    def test_png_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              200, 150)
            with open(path, "rb") as fh:
                data = fh.read()
            result = core.optimize_bytes(
                data, {"width": 100, "quality": 85, "format": "PNG",
                       "crop": None})
            self.assertEqual(result["format"], "PNG")
            self.assertTrue(result["data"].startswith(b"\x89PNG"))

    def test_bad_format_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              100, 100)
            with open(path, "rb") as fh:
                data = fh.read()
            with self.assertRaises(ValueError):
                core.optimize_bytes(
                    data, {"width": None, "quality": 85,
                           "format": "GIF", "crop": None})


if __name__ == "__main__":
    unittest.main()
