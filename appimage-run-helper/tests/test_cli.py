"""CLI tests: in-process main() calls and subprocess runs."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from appimagehelper import cli  # noqa: E402
from tests.helpers import make_fake_appimage, mode_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORGE_PY = "/home/hatch/workspace/forge-v2-testenv/bin/python"


def run_cli(argv):
    """In-process: returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse errors and --help
            code = exc.code if isinstance(exc.code, int) else 0
    return code, out.getvalue(), err.getvalue()


class MakeRunnableCommandTests(unittest.TestCase):

    def test_plain_output_and_bit_set(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        code, out, _err = run_cli(["make-runnable", path])
        self.assertEqual(code, 0)
        self.assertIn("Made", out)
        self.assertIn("runnable", out)
        self.assertEqual(mode_of(path), 0o755)

    def test_json_output(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        code, out, _err = run_cli(["make-runnable", "--json", path])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["command"], "make-runnable")
        self.assertFalse(payload["already"])
        self.assertEqual(payload["mode"], "0o755")
        self.assertIsNone(payload["error"])

    def test_missing_file_exit_1_plain(self):
        code, out, err = run_cli(
            ["make-runnable", "/no/such/file.AppImage"])
        self.assertEqual(code, 1)
        self.assertIn("no file", (out + err).lower())
        self.assertNotIn("Traceback", out + err)

    def test_missing_file_json_error(self):
        code, out, _err = run_cli(
            ["make-runnable", "--json", "/no/such/file.AppImage"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertIn("no file", payload["error"].lower())


class LaunchCommandTests(unittest.TestCase):

    def test_launch_json_finished(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        code, out, _err = run_cli(["launch", "--json", path])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["command"], "launch")
        self.assertTrue(payload["finished"])
        self.assertTrue(payload["made_runnable"])
        self.assertIsNone(payload["error"])

    def test_launch_failure_json(self):
        _tmp, path = make_fake_appimage("exit 5\n")
        code, out, _err = run_cli(["launch", "--json", path])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertIn("stopped right away", payload["error"])


class UsageTests(unittest.TestCase):

    def test_help_exit_0(self):
        code, out, _err = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("make-runnable", out)

    def test_no_args_exit_2(self):
        code, _out, _err = run_cli([])
        self.assertEqual(code, 2)

    def test_version(self):
        code, out, _err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("0.1.0", out)


class DebugReportCommandTests(unittest.TestCase):

    def test_report_written(self):
        import tempfile
        from appimagehelper import logsetup
        tmp = tempfile.mkdtemp()
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = tmp
        try:
            code, out, _err = run_cli(["debug-report"])
        finally:
            if old is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = old
        self.assertEqual(code, 0)
        self.assertIn("Debug report written to", out)
        report_dir = os.path.join(
            tmp, "appimage-run-helper", "logs")
        self.assertTrue(os.path.isdir(report_dir))
        del logsetup


class SubprocessCliTests(unittest.TestCase):
    """The module entry and the wrappers, as a user runs them."""

    def run_module(self, args, **kwargs):
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get(
            "PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "appimagehelper"] + args,
            capture_output=True, text=True, cwd=ROOT, env=env,
            timeout=60, **kwargs)

    def test_module_make_runnable(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        result = self.run_module(["make-runnable", path])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Made", result.stdout)
        self.assertEqual(mode_of(path), 0o755)

    def test_wrapper_make_runnable(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        wrapper = os.path.join(ROOT, "appimage-make-runnable")
        result = subprocess.run(
            ["bash", wrapper, path], capture_output=True,
            text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Made", result.stdout)
        self.assertEqual(mode_of(path), 0o755)

    def test_wrapper_help(self):
        wrapper = os.path.join(ROOT, "appimagehelper-cli")
        result = subprocess.run(
            ["bash", wrapper, "--help"], capture_output=True,
            text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("make-runnable", result.stdout)


class MissingDependencyGuardTests(unittest.TestCase):
    """The GUI missing-dependency guard: block PySide6 with a
    stub package that raises ImportError, run gui_main as a
    subprocess, and require plain words, exit 1, no traceback."""

    def _blocked_env(self, stub_dir):
        stub = os.path.join(stub_dir, "PySide6")
        os.makedirs(stub)
        with open(os.path.join(stub, "__init__.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("raise ImportError('blocked for the test')\n")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [stub_dir, ROOT, env.get("PYTHONPATH", "")])
        env.pop("QT_QPA_PLATFORM", None)
        return env

    def test_gui_main_guard(self):
        import tempfile
        stub_dir = tempfile.mkdtemp(prefix="appimage-block-")
        result = subprocess.run(
            [FORGE_PY, "-m", "appimagehelper.gui_main"],
            capture_output=True, text=True, cwd=ROOT,
            env=self._blocked_env(stub_dir), timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("interface toolkit", result.stderr)
        self.assertIn("Install AppImage Runner", result.stderr)

    def test_gui_main_help_needs_no_qt(self):
        import tempfile
        stub_dir = tempfile.mkdtemp(prefix="appimage-block-")
        result = subprocess.run(
            [FORGE_PY, "-m", "appimagehelper.gui_main", "--help"],
            capture_output=True, text=True, cwd=ROOT,
            env=self._blocked_env(stub_dir), timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("appimage-run", result.stdout)


if __name__ == "__main__":
    unittest.main()
