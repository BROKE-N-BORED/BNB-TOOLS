"""RAM check tests: size parsing, meminfo reading, the verdict.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from preloadchecks import ram  # noqa: E402
import helpers  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2


class ParseSizeTests(unittest.TestCase):
    def test_plain_number_means_gb(self):
        self.assertEqual(ram.parse_size("4"), 4 * GB)
        self.assertEqual(ram.parse_size(4), 4 * GB)

    def test_gb_forms(self):
        self.assertEqual(ram.parse_size("4.5GB"), int(4.5 * GB))
        self.assertEqual(ram.parse_size("4.5 GB"), int(4.5 * GB))
        self.assertEqual(ram.parse_size("4.5g"), int(4.5 * GB))
        self.assertEqual(ram.parse_size("4.5G"), int(4.5 * GB))

    def test_mb_kb_b(self):
        self.assertEqual(ram.parse_size("4096MB"), 4096 * MB)
        self.assertEqual(ram.parse_size("512 MB"), 512 * MB)
        self.assertEqual(ram.parse_size("256KB"), 256 * 1024)
        self.assertEqual(ram.parse_size("1024B"), 1024)

    def test_tb(self):
        self.assertEqual(ram.parse_size("1TB"), 1024 ** 4)

    def test_whitespace_ok(self):
        self.assertEqual(ram.parse_size("  2 GB  "), 2 * GB)

    def test_bad_input(self):
        for bad in ("", "abc", "4XB", "GB", "-1GB", "4.5.6GB",
                    "1e3GB", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ram.parse_size(bad)


class MeminfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "meminfo")
        helpers.write_fake_meminfo(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_meminfo(self):
        values = ram.read_meminfo(self.path)
        self.assertEqual(values["MemTotal"], 8192000)
        self.assertEqual(values["MemAvailable"], 5242880)

    def test_available_uses_mem_available(self):
        self.assertEqual(ram.available_bytes(path=self.path),
                         5242880 * 1024)

    def test_available_falls_back_without_mem_available(self):
        helpers.write_fake_meminfo(
            self.path,
            "MemTotal:        8192000 kB\n"
            "MemFree:         1024000 kB\n"
            "Buffers:          512000 kB\n"
            "Cached:          2048000 kB\n")
        self.assertEqual(ram.available_bytes(path=self.path),
                         (1024000 + 512000 + 2048000) * 1024)

    def test_total(self):
        self.assertEqual(ram.total_bytes(path=self.path),
                         8192000 * 1024)

    def test_missing_file_raises(self):
        with self.assertRaises(OSError):
            ram.read_meminfo(os.path.join(self.tmp.name, "nope"))


class CheckTests(unittest.TestCase):
    MEMINFO = {"MemTotal": 8192000, "MemAvailable": 5242880}

    def test_fits(self):
        result = ram.check(4 * GB, meminfo=self.MEMINFO)
        self.assertTrue(result["fits"])
        self.assertEqual(result["shortfall"], 0)

    def test_reserve_counts(self):
        # 5 GB free, 4.5 GB model: fits without a reserve, does
        # not fit with the 1 GB default reserve.
        result = ram.check(int(4.5 * GB), meminfo=self.MEMINFO)
        self.assertFalse(result["fits"])
        result = ram.check(int(4.5 * GB), reserve_bytes=0,
                           meminfo=self.MEMINFO)
        self.assertTrue(result["fits"])

    def test_shortfall(self):
        result = ram.check(7 * GB, meminfo=self.MEMINFO)
        self.assertFalse(result["fits"])
        self.assertEqual(result["shortfall"],
                         7 * GB + GB - 5242880 * 1024)

    def test_exact_fit(self):
        free = 5242880 * 1024
        result = ram.check(free - GB, meminfo=self.MEMINFO)
        self.assertTrue(result["fits"])

    def test_plain_report_fits(self):
        result = ram.check(4 * GB, meminfo=self.MEMINFO)
        text = ram.plain_report(result)
        self.assertIn("It fits", text)
        self.assertIn("4.0 GB", text)
        self.assertIn("5.0 GB", text)  # free RAM
        self.assertIn("1.0 GB", text)  # reserve

    def test_plain_report_no_fit(self):
        result = ram.check(7 * GB, meminfo=self.MEMINFO)
        text = ram.plain_report(result)
        self.assertIn("It does not fit", text)
        self.assertIn("short", text)


class FormatTests(unittest.TestCase):
    def test_gb(self):
        self.assertEqual(ram.format_gb(int(4.5 * GB)), "4.5 GB")

    def test_mb_under_1gb(self):
        self.assertEqual(ram.format_gb(512 * MB), "512 MB")


if __name__ == "__main__":
    unittest.main()
