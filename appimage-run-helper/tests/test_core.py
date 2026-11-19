"""Core tests: make_runnable and launch against fake AppImages."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from appimagehelper import core  # noqa: E402
from tests.helpers import make_fake_appimage, mode_of  # noqa: E402


class MakeRunnableTests(unittest.TestCase):

    def test_sets_exec_bit(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        self.assertEqual(mode_of(path), 0o644)
        result = core.make_runnable(path)
        self.assertIsNone(result["error"])
        self.assertFalse(result["already"])
        self.assertEqual(result["mode"], "0o755")
        self.assertEqual(mode_of(path), 0o755)
        self.assertEqual(result["path"], os.path.abspath(path))

    def test_already_runnable_is_success(self):
        _tmp, path = make_fake_appimage("exit 0\n", mode=0o755)
        result = core.make_runnable(path)
        self.assertTrue(result["already"])
        self.assertEqual(result["mode"], "0o755")

    def test_keeps_other_bits(self):
        _tmp, path = make_fake_appimage("exit 0\n", mode=0o600)
        result = core.make_runnable(path)
        self.assertEqual(result["mode"], "0o711")
        self.assertEqual(mode_of(path), 0o711)

    def test_missing_file_plain_error(self):
        with self.assertRaises(core.AppImageError) as ctx:
            core.make_runnable("/no/such/file.AppImage")
        self.assertIn("no file", str(ctx.exception).lower())

    def test_directory_plain_error(self):
        with self.assertRaises(core.AppImageError) as ctx:
            core.make_runnable(os.path.expanduser("~"))
        self.assertIn("folder", str(ctx.exception))


class IsAppImageNameTests(unittest.TestCase):

    def test_names(self):
        self.assertTrue(core.is_appimage_name("a/b/C.AppImage"))
        self.assertTrue(core.is_appimage_name("x.appimage"))
        self.assertFalse(core.is_appimage_name("x.AppImage.bak"))
        self.assertFalse(core.is_appimage_name("x"))


class LaunchTests(unittest.TestCase):

    def test_launch_makes_runnable_and_runs(self):
        tmp, path = make_fake_appimage("exit 0\n",
                                       name="Runner.AppImage")
        # Rewrite the fake so running it leaves a marker behind,
        # then sleeps: proof it ran, and proof it kept running.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\necho ran > "%s"\nsleep 2\n'
                     % os.path.join(tmp, "marker.txt"))
        os.chmod(path, 0o644)
        result = core.launch(path)
        self.assertTrue(result["running"])
        self.assertTrue(result["made_runnable"])
        self.assertFalse(result["already"])
        self.assertIsInstance(result["pid"], int)
        deadline = time.time() + 5
        marker = os.path.join(tmp, "marker.txt")
        while time.time() < deadline and not os.path.exists(marker):
            time.sleep(0.05)
        self.assertTrue(os.path.exists(marker))
        self.assertEqual(mode_of(path), 0o755)
        # The sleeper is detached; kill it so the suite leaves
        # nothing running.
        os.kill(result["pid"], 9)

    def test_launch_quick_exit_zero_is_finished(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        result = core.launch(path)
        self.assertTrue(result["finished"])
        self.assertFalse(result["running"])

    def test_launch_instant_failure_plain_error(self):
        _tmp, path = make_fake_appimage("exit 3\n")
        with self.assertRaises(core.AppImageError) as ctx:
            core.launch(path)
        self.assertIn("stopped right away", str(ctx.exception))

    def test_launch_non_program_plain_error(self):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".AppImage")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"this is not a program at all")
        os.chmod(path, 0o644)
        result_mode = core.make_runnable(path)
        self.assertEqual(result_mode["mode"], "0o755")
        with self.assertRaises(core.AppImageError) as ctx:
            core.launch(path, settle=0.1)
        self.assertIn("not a program", str(ctx.exception))

    def test_launch_missing_file_plain_error(self):
        with self.assertRaises(core.AppImageError):
            core.launch("/no/such/file.AppImage")


if __name__ == "__main__":
    unittest.main()
