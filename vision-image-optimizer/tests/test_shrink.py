"""Shrink: resize, quality, crop, never-overwrite-source, and the
shrink CLI (human output, --json, plain errors)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import make_image  # noqa: E402
from optimizer import shrink, tokens  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHRINK_JSON_KEYS = {"path", "width", "height", "tokens_before",
                    "tokens_after", "bytes_before", "bytes_after",
                    "format", "from_cache"}


class ResizeTests(unittest.TestCase):
    def test_resize_result_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "big.png"))
            with open(path, "rb") as fh:
                data = fh.read()
            result = shrink.optimize_bytes(
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
            full = shrink.optimize_bytes(
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
            low = shrink.optimize_bytes(
                data, {"width": None, "quality": 60, "format": "JPEG",
                       "crop": None})
            high = shrink.optimize_bytes(
                data, {"width": None, "quality": 95, "format": "JPEG",
                       "crop": None})
            self.assertLess(low["bytes_after"], high["bytes_after"])

    def test_quality_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              100, 100)
            with open(path, "rb") as fh:
                data = fh.read()
            result = shrink.optimize_bytes(
                data, {"width": None, "quality": 500,
                       "format": "JPEG", "crop": None})
            self.assertGreater(result["bytes_after"], 0)


class CropTests(unittest.TestCase):
    def test_crop_never_crashes_optimize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "pic.png"),
                              200, 150)
            with open(path, "rb") as fh:
                data = fh.read()
            result = shrink.optimize_bytes(
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
            result = shrink.optimize_bytes(
                data, {"width": None, "quality": 85, "format": "JPEG",
                       "crop": (0, 0, 200, 150)})
            self.assertEqual((result["width"], result["height"]),
                             (200, 150))
            self.assertEqual(result["tokens_after"],
                             tokens.vision_tokens(200, 150))


class NeverOverwriteTests(unittest.TestCase):
    def test_output_goes_to_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "shot.png"))
            dest = shrink.output_path(path, None, 512, "JPEG")
            self.assertEqual(os.path.dirname(dest),
                             os.path.join(tmp, "optimized"))
            self.assertNotEqual(os.path.abspath(dest),
                                os.path.abspath(path))

    def test_output_never_equals_source(self):
        # The output name always carries a size suffix, so it can
        # never be the source name, checked across the awkward
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
                dest = shrink.output_path(path, tmp, width, fmt)
                self.assertNotEqual(os.path.abspath(dest),
                                    os.path.abspath(path),
                                    name)

    def test_write_never_touches_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_image(os.path.join(tmp, "shot.png"))
            with open(path, "rb") as fh:
                before = fh.read()
            dest, _ = shrink.write_optimized(
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
            result = shrink.optimize_bytes(
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
                shrink.optimize_bytes(
                    data, {"width": None, "quality": 85,
                           "format": "GIF", "crop": None})


class ShrinkCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                                   "config")
        self.env["XDG_CACHE_HOME"] = os.path.join(self.tmp.name,
                                                  "cache")
        self.env["QT_QPA_PLATFORM"] = "offscreen"
        self.env["TMPDIR"] = "/tmp"
        self.img = make_image(os.path.join(self.tmp.name, "shot.png"),
                              1920, 1080)

    def tearDown(self):
        self.tmp.cleanup()

    def run_shrink(self, args, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "optimizer.shrink"] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def test_help_exit_0(self):
        proc = self.run_shrink(["--help"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: vision-shrink", proc.stdout)
        self.assertIn("--json", proc.stdout)

    def test_human_output_matches_v01(self):
        proc = self.run_shrink([self.img, "--width", "512"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Wrote ", proc.stdout)
        self.assertIn("Size: ", proc.stdout)
        self.assertIn("Vision tokens: 2040 to 144", proc.stdout)
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out))

    def test_json_output_schema(self):
        proc = self.run_shrink([self.img, "--width", "512", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(set(data), SHRINK_JSON_KEYS)
        self.assertEqual(data["width"], 512)
        self.assertEqual(data["height"], 288)
        self.assertEqual(data["tokens_before"], 2040)
        self.assertEqual(data["tokens_after"], 144)
        self.assertEqual(data["bytes_before"],
                         os.path.getsize(self.img))
        self.assertEqual(data["bytes_after"],
                         os.path.getsize(data["path"]))
        self.assertEqual(data["format"], "JPEG")
        self.assertFalse(data["from_cache"])
        self.assertTrue(os.path.exists(data["path"]))

    def test_json_second_run_reports_from_cache(self):
        self.run_shrink([self.img, "--width", "512", "--json"])
        proc = self.run_shrink([self.img, "--width", "512", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["from_cache"])

    def test_no_cache_skips_cache(self):
        self.run_shrink([self.img, "--width", "512"])
        proc = self.run_shrink([self.img, "--width", "512",
                                "--no-cache", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertFalse(data["from_cache"])

    def test_missing_file_is_plain_error_exit_1(self):
        proc = self.run_shrink(["/no/such/file.png"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No such file", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_bad_crop_is_plain_error_exit_1(self):
        proc = self.run_shrink([self.img, "--crop", "1,2,3"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("crop needs four numbers", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_bad_format_choice_exit_1(self):
        proc = self.run_shrink([self.img, "--format", "GIF"])
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
