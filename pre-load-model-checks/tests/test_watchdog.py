"""Watchdog tests: pass-through, exit codes, quiet kills.
"""

import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from preloadchecks import watchdog  # noqa: E402

PY = sys.executable


def py_cmd(code):
    """A Python one-liner as a command list, unbuffered."""
    return [PY, "-u", "-c", code]


class PassThroughTests(unittest.TestCase):
    def test_output_passes_through_live(self):
        out = io.StringIO()
        code = watchdog.run(
            py_cmd("print('hello'); print('world')"),
            quiet_seconds=10, out=out)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "hello\nworld\n")

    def test_exit_code_passes_through(self):
        out = io.StringIO()
        code = watchdog.run(py_cmd("import sys; sys.exit(3)"),
                            quiet_seconds=10, out=out)
        self.assertEqual(code, 3)

    def test_stderr_joins_stdout(self):
        out = io.StringIO()
        code = watchdog.run(
            py_cmd("import sys; print('err', file=sys.stderr)"),
            quiet_seconds=10, out=out)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "err\n")


class QuietKillTests(unittest.TestCase):
    def test_silent_command_is_stopped(self):
        out = io.StringIO()
        code = watchdog.run(
            py_cmd("import time; time.sleep(30)"),
            quiet_seconds=1, out=out)
        self.assertEqual(code, watchdog.QUIET_KILLED_EXIT)
        self.assertEqual(code, 124)

    def test_quiet_message_says_second_not_seconds_for_one(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = watchdog.run(
                py_cmd("import time; time.sleep(30)"),
                quiet_seconds=1, out=out)
        self.assertEqual(code, 124)
        self.assertIn("went quiet for 1 second ",
                      err.getvalue())

    def test_quiet_message_says_seconds_for_more_than_one(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = watchdog.run(
                py_cmd("import time; time.sleep(30)"),
                quiet_seconds=2, out=out)
        self.assertEqual(code, 124)
        self.assertIn("went quiet for 2 seconds ",
                      err.getvalue())

    def test_command_that_talks_then_goes_quiet_is_stopped(self):
        # A 3-second quiet window: on a loaded machine the
        # child can take over a second just to start, and the
        # test is about the quiet kill, not startup speed.
        out = io.StringIO()
        code = watchdog.run(
            py_cmd("print('starting'); import time; "
                   "time.sleep(30)"),
            quiet_seconds=3, out=out)
        self.assertEqual(code, 124)
        self.assertIn("starting", out.getvalue())

    def test_periodic_output_keeps_it_alive(self):
        # Prints every 0.3s for 1.5s: never quiet for 2s.
        out = io.StringIO()
        code = watchdog.run(
            py_cmd("import time\n"
                   "[print('tick', flush=True) or time.sleep(0.3) "
                   "for _ in range(5)]"),
            quiet_seconds=2, out=out)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().count("tick"), 5)


class ErrorTests(unittest.TestCase):
    def test_missing_command_is_exit_2(self):
        out = io.StringIO()
        code = watchdog.run(["no-such-command-anywhere-xyz"],
                            quiet_seconds=10, out=out)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
