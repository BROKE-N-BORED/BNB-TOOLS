"""Chain test: the pieces chain, each runnable alone.

make-runnable (piece 1) sets the bit; launch (piece 2's engine)
runs the now-runnable file; the marker proves the file actually
ran. Then launch alone on a fresh file proves it does both steps
without the first piece.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from appimagehelper import core  # noqa: E402
from tests.helpers import make_fake_appimage, mode_of  # noqa: E402


def _wait_for(path, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


class ChainTests(unittest.TestCase):

    def test_make_runnable_then_launch(self):
        tmp, path = make_fake_appimage("exit 0\n")
        marker = os.path.join(tmp, "chained.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\necho ok > "%s"\n' % marker)
        os.chmod(path, 0o644)

        # Piece 1 alone: the bit is set, nothing ran.
        made = core.make_runnable(path)
        self.assertFalse(made["already"])
        self.assertEqual(mode_of(path), 0o755)
        self.assertFalse(os.path.exists(marker))

        # Piece 2 on the now-runnable file: it runs.
        result = core.launch(path)
        self.assertTrue(result["already"])
        self.assertFalse(result["made_runnable"])
        self.assertTrue(result["finished"])
        self.assertTrue(_wait_for(marker))

    def test_launch_alone_does_both_steps(self):
        tmp, path = make_fake_appimage("exit 0\n")
        marker = os.path.join(tmp, "solo.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\necho ok > "%s"\n' % marker)
        os.chmod(path, 0o644)
        result = core.launch(path)
        self.assertTrue(result["made_runnable"])
        self.assertEqual(mode_of(path), 0o755)
        self.assertTrue(_wait_for(marker))


if __name__ == "__main__":
    unittest.main()
