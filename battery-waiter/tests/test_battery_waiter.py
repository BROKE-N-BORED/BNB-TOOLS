"""Tests for battery-waiter (T34). No network, no real machine load.

Threshold tests use injected fake readings, never the live load
average. Max-wait tests use timeouts of a fraction of a second,
never a real 45-minute wait.
"""

import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import battery_waiter
from battery_waiter import LoadReading, describe, format_duration
from battery_waiter import parse_loadavg_text, read_load
from battery_waiter import read_tmp_free_mb, wait_for_window
from battery_waiter import window_clear

MAX_LOAD = 2.5
MAX_RUNNABLE = 4
MIN_TMP_MB = 300


def quiet():
    return LoadReading(1.20, 1.10, 2)


def busy_load1():
    return LoadReading(9.00, 1.10, 2)


def busy_load5():
    return LoadReading(1.20, 9.00, 2)


def busy_runnable():
    return LoadReading(1.20, 1.10, 20)


def check(reading, tmp_mb=500.0):
    return window_clear(reading, tmp_mb, MAX_LOAD, MAX_RUNNABLE,
                        MIN_TMP_MB)


class ParseLoadavgTests(unittest.TestCase):

    def test_parses_full_line(self):
        reading = parse_loadavg_text("2.49 6.12 4.01 16/512 12345")
        self.assertIsNotNone(reading)
        self.assertAlmostEqual(reading.load1, 2.49)
        self.assertAlmostEqual(reading.load5, 6.12)

    def test_parses_runnable_count(self):
        reading = parse_loadavg_text("0.50 0.40 0.30 3/418 999")
        self.assertEqual(reading.runnable, 3)

    def test_short_line_returns_none(self):
        self.assertIsNone(parse_loadavg_text("0.50 0.40"))
        self.assertIsNone(parse_loadavg_text(""))

    def test_bad_numbers_return_none(self):
        self.assertIsNone(parse_loadavg_text("xx yy zz 1/2 3"))
        self.assertIsNone(parse_loadavg_text("0.5 0.4 0.3 oo/2 3"))


class WindowClearTests(unittest.TestCase):

    def test_clear(self):
        clear, blockers = check(quiet())
        self.assertTrue(clear)
        self.assertEqual(blockers, [])

    def test_load1_high(self):
        clear, blockers = check(busy_load1())
        self.assertFalse(clear)
        self.assertEqual(blockers, ["load1"])

    def test_load5_high(self):
        clear, blockers = check(busy_load5())
        self.assertFalse(clear)
        self.assertEqual(blockers, ["load5"])

    def test_runnable_high(self):
        clear, blockers = check(busy_runnable())
        self.assertFalse(clear)
        self.assertEqual(blockers, ["runnable"])

    def test_tmp_low(self):
        clear, blockers = check(quiet(), tmp_mb=19.0)
        self.assertFalse(clear)
        self.assertEqual(blockers, ["tmp"])

    def test_load_at_threshold_blocks(self):
        # The rule is strictly under 2.5: exactly 2.5 is not quiet.
        reading = LoadReading(2.5, 2.5, 1)
        clear, blockers = check(reading)
        self.assertFalse(clear)
        self.assertEqual(blockers, ["load1", "load5"])

    def test_tmp_at_minimum_clears(self):
        clear, blockers = check(quiet(), tmp_mb=300.0)
        self.assertTrue(clear)
        self.assertEqual(blockers, [])

    def test_runnable_at_max_blocks(self):
        reading = LoadReading(1.0, 1.0, 4)
        clear, blockers = check(reading)
        self.assertFalse(clear)
        self.assertEqual(blockers, ["runnable"])

    def test_runnable_unknown_skipped(self):
        # No /proc on some systems: runnable unknown is not a blocker.
        reading = LoadReading(1.0, 1.0, None)
        clear, blockers = check(reading)
        self.assertTrue(clear)
        self.assertEqual(blockers, [])

    def test_load_unknown_blocks(self):
        clear, blockers = check(None)
        self.assertFalse(clear)
        self.assertEqual(blockers, ["load unknown"])

    def test_tmp_unknown_blocks(self):
        clear, blockers = check(quiet(), tmp_mb=None)
        self.assertFalse(clear)
        self.assertEqual(blockers, ["tmp unknown"])


class FormatDurationTests(unittest.TestCase):

    def test_seconds(self):
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(0), "0s")

    def test_minutes(self):
        self.assertEqual(format_duration(150), "2m 30s")
        self.assertEqual(format_duration(2700), "45m 00s")

    def test_hours(self):
        self.assertEqual(format_duration(3900), "1h 05m")


class DescribeTests(unittest.TestCase):

    def test_unknown_values_show_question_marks(self):
        text = describe(None, None)
        self.assertIn("load1 ?", text)
        self.assertIn("runnable ?", text)
        self.assertIn("tmp ?", text)
        text = describe(LoadReading(1.0, 1.0, None), 412.7)
        self.assertIn("runnable ?", text)
        self.assertIn("tmp 412 MB free", text)


class WaitForWindowTests(unittest.TestCase):

    def run_wait(self, probe, max_wait_s=5.0, interval_s=0.01):
        out = io.StringIO()
        result = wait_for_window(
            probe, max_wait_s, interval_s, MAX_LOAD, MAX_RUNNABLE,
            MIN_TMP_MB, out)
        return result, out.getvalue()

    def test_clear_at_once(self):
        probe = lambda: (quiet(), 500.0)  # noqa: E731
        (outcome, waited, _r, _t), text = self.run_wait(probe)
        self.assertEqual(outcome, "clear")
        self.assertLess(waited, 1.0)
        self.assertIn("Window clear", text)
        self.assertNotIn("still busy", text)

    def test_busy_then_clear(self):
        readings = [(busy_load1(), 500.0), (busy_load1(), 500.0),
                    (quiet(), 500.0)]
        state = {"n": 0}

        def probe():
            reading = readings[min(state["n"], len(readings) - 1)]
            state["n"] += 1
            return reading

        (outcome, _w, _r, _t), text = self.run_wait(probe)
        self.assertEqual(outcome, "clear")
        self.assertIn("still busy", text)
        self.assertIn("Waiting on: load1", text)
        self.assertIn("load1 9.00", text)
        self.assertIn("Window clear", text)

    def test_max_wait_expires(self):
        probe = lambda: (busy_load1(), 500.0)  # noqa: E731
        (outcome, waited, _r, _t), text = self.run_wait(
            probe, max_wait_s=0.3, interval_s=0.05)
        self.assertEqual(outcome, "expired")
        self.assertGreaterEqual(waited, 0.25)
        self.assertIn("Max wait", text)
        self.assertIn("Running the command anyway", text)

    def test_expiry_names_blockers(self):
        probe = lambda: (busy_runnable(), 19.0)  # noqa: E731
        (_o, _w, _r, _t), text = self.run_wait(
            probe, max_wait_s=0.2, interval_s=0.05)
        self.assertIn("Waiting on: runnable, tmp", text)


class MainTests(unittest.TestCase):

    def run_main(self, argv, probe=None):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = battery_waiter.main(argv, out=out, probe=probe)
        return code, out.getvalue(), err.getvalue()

    def test_help_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                battery_waiter.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        text = out.getvalue()
        self.assertIn("quiet window", text)
        self.assertNotIn("\u2014", text)

    def test_version_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                battery_waiter.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("battery-waiter 0.1.0", out.getvalue())

    def test_no_command(self):
        code, _out, err = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("no command given", err)
        self.assertNotIn("Traceback", err)

    def test_command_not_found(self):
        code, _out, err = self.run_main(
            ["--", "definitely-not-a-real-command-xyz"])
        self.assertEqual(code, 1)
        self.assertIn("command not found", err)
        self.assertIn("definitely-not-a-real-command-xyz", err)
        self.assertNotIn("Traceback", err)

    def test_exit_code_zero_passes_through(self):
        probe = lambda: (quiet(), 500.0)  # noqa: E731
        code, out, _err = self.run_main(
            [sys.executable, "-c", "pass"], probe=probe)
        self.assertEqual(code, 0)
        self.assertIn("exit code 0", out)

    def test_exit_code_nonzero_passes_through(self):
        probe = lambda: (quiet(), 500.0)  # noqa: E731
        code, out, _err = self.run_main(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            probe=probe)
        self.assertEqual(code, 3)
        self.assertIn("exit code 3", out)

    def test_runs_anyway_after_max_wait(self):
        probe = lambda: (busy_load1(), 500.0)  # noqa: E731
        code, out, _err = self.run_main(
            ["--max-wait", "0.01", "--interval", "0.05",
             sys.executable, "-c", "pass"],
            probe=probe)
        self.assertEqual(code, 0)
        self.assertIn("Max wait", out)
        self.assertIn("Running the command anyway", out)
        self.assertIn("Done: waited", out)

    def test_status_lines_name_blockers_and_numbers(self):
        readings = [(busy_load1(), 412.0), (quiet(), 412.0)]
        state = {"n": 0}

        def probe():
            reading = readings[min(state["n"], len(readings) - 1)]
            state["n"] += 1
            return reading

        code, out, _err = self.run_main(
            ["--interval", "0.01", sys.executable, "-c", "pass"],
            probe=probe)
        self.assertEqual(code, 0)
        self.assertIn("Will run:", out)
        self.assertIn("Waiting on: load1", out)
        self.assertIn("load1 9.00", out)
        self.assertIn("tmp 412 MB free", out)
        self.assertIn("Window clear", out)
        self.assertNotIn("\u2014", out)

    def test_bad_max_wait(self):
        code, _out, err = self.run_main(
            ["--max-wait", "0", sys.executable, "-c", "pass"])
        self.assertEqual(code, 1)
        self.assertIn("--max-wait", err)
        self.assertNotIn("Traceback", err)

    def test_not_executable_file(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False) as fh:
            fh.write("#!/bin/sh\nexit 0\n")
            path = fh.name
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            code, _out, err = self.run_main(["--", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 1)
        self.assertIn("not executable", err)
        self.assertNotIn("Traceback", err)

    def test_debug_report_written(self):
        probe = lambda: (quiet(), 500.0)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmpdir:
            report = os.path.join(tmpdir, "report.txt")
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                code, out, _err = self.run_main(
                    ["--debug-report", report,
                     sys.executable, "-c", "pass"],
                    probe=probe)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(report))
            with open(report, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("battery-waiter", text)
            self.assertIn("max_load", text)
            self.assertIn("Debug report written to", out)
            # The log dir lives in a temp dir, never in the tree.
            self.assertFalse(os.path.isdir(
                os.path.join(tmpdir, "logs")))

    def test_debug_report_unwritable_warns(self):
        probe = lambda: (quiet(), 500.0)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmpdir:
            report = os.path.join(tmpdir, "no-such-dir", "report.txt")
            code, out, _err = self.run_main(
                ["--debug-report", report,
                 sys.executable, "-c", "pass"],
                probe=probe)
        self.assertEqual(code, 0)
        self.assertIn("Warning: could not write the debug report", out)


class RealReadingsTests(unittest.TestCase):
    """Shape checks against the live machine. No fixed values."""

    def test_tmp_free_is_positive_number(self):
        free = read_tmp_free_mb("/tmp")
        self.assertIsNotNone(free)
        self.assertGreater(free, 0)

    def test_load_reading_shape(self):
        reading = read_load()
        if reading is None:
            self.skipTest("load average not readable here")
        self.assertGreaterEqual(reading.load1, 0)
        self.assertGreaterEqual(reading.load5, 0)
        if reading.runnable is not None:
            self.assertGreaterEqual(reading.runnable, 0)


if __name__ == "__main__":
    unittest.main()
