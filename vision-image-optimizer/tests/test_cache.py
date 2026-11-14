"""Cache: same image + settings = hit; anything changed = miss."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import make_image  # noqa: E402
from optimizer.cache import ImageCache  # noqa: E402
from optimizer.shrink import optimize_bytes  # noqa: E402

SETTINGS = {"width": 512, "quality": 85, "format": "JPEG",
            "crop": None}


class OptimizedCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = ImageCache(self.tmp.name)
        self.img_path = make_image(
            os.path.join(self.tmp.name, "pic.png"), 640, 480)
        with open(self.img_path, "rb") as fh:
            self.image_bytes = fh.read()
        self.result = optimize_bytes(self.image_bytes, SETTINGS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_image_and_settings_is_hit(self):
        self.cache.put_optimized(self.image_bytes, SETTINGS,
                                 self.result)
        hit = self.cache.get_optimized(self.image_bytes, SETTINGS)
        self.assertIsNotNone(hit)
        self.assertTrue(hit["from_cache"])
        self.assertEqual(hit["data"], self.result["data"])
        self.assertEqual(hit["tokens_after"],
                         self.result["tokens_after"])

    def test_changed_settings_is_miss(self):
        self.cache.put_optimized(self.image_bytes, SETTINGS,
                                 self.result)
        other = dict(SETTINGS, quality=60)
        self.assertIsNone(self.cache.get_optimized(self.image_bytes,
                                                   other))
        other = dict(SETTINGS, width=768)
        self.assertIsNone(self.cache.get_optimized(self.image_bytes,
                                                   other))

    def test_changed_image_is_miss(self):
        self.cache.put_optimized(self.image_bytes, SETTINGS,
                                 self.result)
        other_path = make_image(
            os.path.join(self.tmp.name, "other.png"), 640, 480,
            noise=True)
        with open(other_path, "rb") as fh:
            other_bytes = fh.read()
        self.assertIsNone(self.cache.get_optimized(other_bytes,
                                                   SETTINGS))

    def test_clear_empties_cache(self):
        self.cache.put_optimized(self.image_bytes, SETTINGS,
                                 self.result)
        self.cache.put_description(
            self.result["data"], "prompt", "fast", "smart",
            {"text": "hello world, this is a description",
             "model_used": "fast"})
        removed, freed = self.cache.clear()
        self.assertGreater(removed, 0)
        self.assertGreater(freed, 0)
        self.assertIsNone(self.cache.get_optimized(self.image_bytes,
                                                   SETTINGS))
        self.assertIsNone(self.cache.get_description(
            self.result["data"], "prompt", "fast", "smart"))
        self.assertEqual(self.cache.stats(), (0, 0, 0))

    def test_disabled_cache_never_hits(self):
        cache = ImageCache(self.tmp.name, enabled=False)
        cache.put_optimized(self.image_bytes, SETTINGS, self.result)
        self.assertIsNone(cache.get_optimized(self.image_bytes,
                                              SETTINGS))

    def test_cache_survives_restart(self):
        self.cache.put_optimized(self.image_bytes, SETTINGS,
                                 self.result)
        self.cache.put_description(
            self.result["data"], "prompt", "fast", "smart",
            {"text": "hello world, this is a description",
             "model_used": "fast"})
        # A brand-new process reads the old entries off disk.
        tree = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        script = (
            "import sys; sys.path.insert(0, %r);"
            "from optimizer.cache import ImageCache;"
            "cache = ImageCache(%r);"
            "data = open(%r, 'rb').read();"
            "hit = cache.get_optimized(data, %r);"
            "assert hit is not None and hit['from_cache'], 'opt miss';"
            "desc = cache.get_description(hit['data'], 'prompt',"
            " 'fast', 'smart');"
            "assert desc is not None and desc['from_cache'],"
            " 'desc miss';"
            "print('restart hit OK')"
            % (tree, self.tmp.name, self.img_path, SETTINGS))
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("restart hit OK", proc.stdout)


class DescriptionCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = ImageCache(self.tmp.name)
        self.opt_bytes = b"fake-optimized-bytes"

    def tearDown(self):
        self.tmp.cleanup()

    def test_description_hit_and_miss(self):
        record = {"text": "A red bicycle by a wall.",
                  "model_used": "minicpm-v"}
        self.cache.put_description(self.opt_bytes, "prompt",
                                   "minicpm-v", "qwen3-vl:2b-instruct",
                                   record)
        hit = self.cache.get_description(
            self.opt_bytes, "prompt", "minicpm-v",
            "qwen3-vl:2b-instruct")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["text"], record["text"])
        self.assertTrue(hit["from_cache"])
        # Changed prompt = miss.
        self.assertIsNone(self.cache.get_description(
            self.opt_bytes, "other prompt", "minicpm-v",
            "qwen3-vl:2b-instruct"))
        # Changed model = miss.
        self.assertIsNone(self.cache.get_description(
            self.opt_bytes, "prompt", "other-model",
            "qwen3-vl:2b-instruct"))


if __name__ == "__main__":
    unittest.main()
