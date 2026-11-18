"""CLI tests: every subcommand, exit codes, plain errors.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from preloadchecks import cli  # noqa: E402
import helpers  # noqa: E402


def run_cli(argv):
    """Run cli.main with captured output: (exit code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out):
        with contextlib.redirect_stderr(err):
            code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class RamCliTests(unittest.TestCase):
    def test_tiny_model_fits(self):
        # Reserve 0: on a loaded machine free RAM can dip under
        # the 1 GB default reserve, which would make even a tiny
        # model "not fit" through no fault of the check.
        code, out, _err = run_cli(
            ["ram", "--require", "1KB", "--reserve", "0"])
        self.assertEqual(code, 0)
        self.assertIn("It fits", out)

    def test_huge_model_does_not_fit(self):
        code, out, _err = run_cli(["ram", "--require", "999999GB"])
        self.assertEqual(code, 1)
        self.assertIn("It does not fit", out)

    def test_json_shape(self):
        code, out, _err = run_cli(
            ["ram", "--require", "1KB", "--reserve", "0",
             "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["fits"])
        self.assertIn("available_gb", data)
        self.assertIn("total_gb", data)

    def test_bad_size_is_exit_2_plain_words(self):
        code, _out, err = run_cli(["ram", "--require", "banana"])
        self.assertEqual(code, 2)
        self.assertIn("does not make sense", err)
        self.assertNotIn("Traceback", err)

    def test_bad_reserve_is_exit_2(self):
        code, _out, err = run_cli(
            ["ram", "--require", "1KB", "--reserve", "banana"])
        self.assertEqual(code, 2)
        self.assertIn("does not make sense", err)

    def test_missing_require_is_argparse_exit_2(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(["ram"])
        self.assertEqual(ctx.exception.code, 2)


class ProcessesCliTests(unittest.TestCase):
    def test_lists_processes(self):
        code, out, _err = run_cli(["processes", "--limit", "2"])
        self.assertEqual(code, 0)
        self.assertIn("PID", out)

    def test_json_parses(self):
        code, out, _err = run_cli(
            ["processes", "--limit", "2", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertLessEqual(len(data), 2)
        if data:
            self.assertIn("pid", data[0])
            self.assertIn("name", data[0])

    def test_limit_out_of_range_is_exit_2(self):
        for bad in ("0", "21"):
            with self.subTest(limit=bad):
                code, _out, err = run_cli(
                    ["processes", "--limit", bad])
                self.assertEqual(code, 2)
                self.assertIn("between 1 and 20", err)


class SuitabilityCliTests(unittest.TestCase):
    CARD = {"name": "example-7b", "size_gb": 4.5,
            "capabilities": ["chat", "code"],
            "context_tokens": 32768}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.card = os.path.join(self.tmp.name, "card.json")
        with open(self.card, "w", encoding="utf-8") as fh:
            json.dump(self.CARD, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def _task(self, data):
        path = os.path.join(self.tmp.name, "task.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_suitable_task_file(self):
        task = self._task({"needs_capabilities": ["code"]})
        code, out, _err = run_cli(
            ["suitability", "--card", self.card, "--task", task])
        self.assertEqual(code, 0)
        self.assertIn("looks able", out)

    def test_unsuitable_task_file(self):
        task = self._task({"needs_capabilities": ["vision"]})
        code, out, _err = run_cli(
            ["suitability", "--card", self.card, "--task", task])
        self.assertEqual(code, 1)
        self.assertIn("Do not load", out)

    def test_flags_form(self):
        code, _out, _err = run_cli(
            ["suitability", "--card", self.card,
             "--needs-capability", "code", "--min-context", "8192",
             "--max-size", "6GB"])
        self.assertEqual(code, 0)

    def test_flags_form_unsuitable(self):
        code, _out, _err = run_cli(
            ["suitability", "--card", self.card,
             "--needs-capability", "vision"])
        self.assertEqual(code, 1)

    def test_bad_max_size_is_exit_2(self):
        code, _out, err = run_cli(
            ["suitability", "--card", self.card,
             "--max-size", "banana"])
        self.assertEqual(code, 2)
        self.assertIn("does not make sense", err)

    def test_missing_card_is_exit_2(self):
        code, _out, err = run_cli(
            ["suitability", "--card",
             os.path.join(self.tmp.name, "nope.json")])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_invalid_card_json_is_exit_2(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        code, _out, err = run_cli(["suitability", "--card", bad])
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_json_output(self):
        code, out, _err = run_cli(
            ["suitability", "--card", self.card,
             "--needs-capability", "code", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["model"], "example-7b")
        self.assertTrue(data["suitable"])


class KillCliTests(unittest.TestCase):
    def setUp(self):
        self.victims = []

    def tearDown(self):
        for pid in self.victims:
            helpers.stop_pid(pid)

    def test_no_pid_is_exit_2(self):
        code, _out, err = run_cli(["kill", "--confirm"])
        self.assertEqual(code, 2)
        self.assertIn("at least one process", err)

    def test_no_confirm_is_exit_2(self):
        code, _out, err = run_cli(["kill", "--pid", "12345"])
        self.assertEqual(code, 2)
        self.assertIn("--confirm", err)

    def test_dry_run_reports_without_stopping(self):
        pid = helpers.spawn_detached_victim(seconds=30)
        self.victims.append(pid)
        code, out, _err = run_cli(
            ["kill", "--pid", str(pid), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Would stop", out)
        self.assertTrue(helpers._pid_exists(pid))

    def test_confirm_stops_a_throwaway_process(self):
        pid = helpers.spawn_detached_victim(seconds=60)
        self.victims.append(pid)
        code, out, _err = run_cli(
            ["kill", "--pid", str(pid), "--confirm"])
        self.assertEqual(code, 0)
        self.assertIn("Stopped", out)
        helpers.assert_stopped(self, pid)
        self.victims.remove(pid)

    def test_pid_1_refused_with_exit_1(self):
        code, out, _err = run_cli(["kill", "--pid", "1",
                                   "--confirm"])
        self.assertEqual(code, 1)
        self.assertIn("Did not stop", out)


class WatchdogCliTests(unittest.TestCase):
    def test_watchdog_passes_exit_code(self):
        code, out, _err = run_cli(
            ["watchdog", "--quiet-seconds", "10", "--",
             sys.executable, "-u", "-c", "print('hi')"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "hi\n")

    def test_watchdog_quiet_kill_is_124(self):
        code, _out, _err = run_cli(
            ["watchdog", "--quiet-seconds", "1", "--",
             sys.executable, "-u", "-c",
             "import time; time.sleep(30)"])
        self.assertEqual(code, 124)

    def test_watchdog_without_command_is_exit_2(self):
        code, _out, err = run_cli(["watchdog"])
        self.assertEqual(code, 2)
        self.assertIn("Give a command", err)


class TopLevelTests(unittest.TestCase):
    def test_version(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("0.1.0", out.getvalue())

    def test_no_command_is_exit_2(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_debug_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("XDG_DATA_HOME")
            os.environ["XDG_DATA_HOME"] = tmp
            try:
                code, out, _err = run_cli(["debug-report"])
            finally:
                if old is None:
                    del os.environ["XDG_DATA_HOME"]
                else:
                    os.environ["XDG_DATA_HOME"] = old
        self.assertEqual(code, 0)
        self.assertIn("pre-load-model-checks", out)
        self.assertIn("0.1.0", out)


if __name__ == "__main__":
    unittest.main()
