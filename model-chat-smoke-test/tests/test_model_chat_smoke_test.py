"""Tests for model-chat-smoke-test (BNB-TOOLS T38).

No network, no real model: every run goes through tests/mock_engine.py,
the labeled test fixture, which replies, hangs, errors, or stays
silent on demand. Hang tests use a one-prompt file and a 2-second
timeout, so the whole suite stays fast.
"""

import hashlib
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_DIR = HERE.parent
CLI = TOOL_DIR / "model_chat_smoke_test.py"
MOCK = HERE / "mock_engine.py"

sys.path.insert(0, str(TOOL_DIR))
import model_chat_smoke_test as mcs  # noqa: E402

DEBUG_LOG_SHA = ("d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029"
                 "ab69ec19e73a2")

# The fixed S6 desktop template Exec line (2026-11-14 fix): the
# empty-%k fallback uses os.getcwd() directly, never dirname() on it.
FIXED_EXEC = (
    'Exec=python3 -c "import os, sys, subprocess; a = sys.argv[1] '
    "if len(sys.argv) > 1 and sys.argv[1] else ''; "
    "d = os.path.dirname(a) if a else os.getcwd(); "
    "subprocess.call(['bash', os.path.join(d, 'install.sh')])\" %k"
)


def mock_template(mode, extra=""):
    """An engine template that runs the mock in the given mode."""
    cmd = "%s %s --mode %s --model {model} --prompt {prompt}" % (
        sys.executable, MOCK, mode)
    if extra:
        cmd += " " + extra
    return cmd


def run_cli(*args, **kwargs):
    """Run the CLI as a subprocess. Returns the CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(CLI), *[str(a) for a in args]],
        capture_output=True, text=True, timeout=120, **kwargs)


def write_lines(directory, name, lines):
    path = Path(directory) / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestHelpAndVersion(unittest.TestCase):

    def test_help_exits_zero(self):
        proc = run_cli("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("canned chat", proc.stdout)

    def test_version_prints_version(self):
        proc = run_cli("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0.1.0", proc.stdout)

    def test_no_args_is_plain_usage_error(self):
        proc = run_cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no engine command given", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestListPrompts(unittest.TestCase):

    def test_list_prompts_prints_builtins(self):
        proc = run_cli("--list-prompts")
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.strip().split("\n")
        self.assertEqual(lines, mcs.BUILTIN_PROMPTS)
        self.assertEqual(len(lines), 3)

    def test_list_prompts_with_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = write_lines(tmp, "p.txt",
                               ["first prompt", "# a comment", "",
                                "second prompt"])
            proc = run_cli("--list-prompts", "--prompts", path)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip().split("\n"),
                         ["first prompt", "second prompt"])

    def test_list_prompts_missing_file(self):
        proc = run_cli("--list-prompts", "--prompts", "no-such-file.txt")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestDryRun(unittest.TestCase):

    def test_dry_run_lists_every_command(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha", "beta", "--dry-run")
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.strip().split("\n")
        self.assertEqual(len(lines), 6)  # 2 models x 3 prompts
        self.assertTrue(all("alpha" in line or "beta" in line
                            for line in lines))

    def test_dry_run_runs_nothing(self):
        # A hang-mode mock would stall for the timeout if it ran.
        started = time.monotonic()
        proc = run_cli("--engine", mock_template("hang"),
                       "--models", "alpha", "--dry-run")
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 0)
        self.assertLess(elapsed, 5.0)

    def test_dry_run_shell_quotes_values(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "my model", "--dry-run")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("'my model'", proc.stdout)

    def test_dry_run_needs_engine_and_models(self):
        proc = run_cli("--dry-run")
        self.assertEqual(proc.returncode, 2)
        proc = run_cli("--engine", mock_template("reply"), "--dry-run")
        self.assertEqual(proc.returncode, 2)

    def test_dry_run_works_without_the_engine_installed(self):
        # The point of a dry run is to check the template: it must
        # not demand the engine be installed first.
        proc = run_cli("--engine",
                       "fyrn chat --model {model} --prompt {prompt}",
                       "--models", "tiny-1b", "--dry-run")
        self.assertEqual(proc.returncode, 0)
        # shlex.quote leaves a plain name unquoted and quotes the
        # prompt: the command must still be the full template.
        self.assertIn("fyrn chat --model tiny-1b --prompt 'Hello. "
                      "Reply with one short sentence.'", proc.stdout)


class TestTemplateValidation(unittest.TestCase):

    def test_missing_model_placeholder(self):
        proc = run_cli("--engine", "echo {prompt}",
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("{model}", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_prompt_placeholder(self):
        proc = run_cli("--engine", "echo {model}",
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("{prompt}", proc.stderr)

    def test_unbalanced_quotes(self):
        proc = run_cli("--engine", 'echo "unterminated {model} {prompt}',
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unbalanced quotes", proc.stderr)

    def test_empty_engine_template(self):
        proc = run_cli("--engine", "", "--models", "alpha")
        self.assertEqual(proc.returncode, 2)


class TestEngineGuard(unittest.TestCase):
    """The missing-dependency guard: a missing engine command is a
    plain-words error naming the command, exit 1, never a traceback."""

    def test_missing_command(self):
        proc = run_cli(
            "--engine",
            "no-such-engine-xyz-12345 --model {model} --prompt {prompt}",
            "--models", "alpha")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot find the engine command", proc.stderr)
        self.assertIn("no-such-engine-xyz-12345", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_command_with_path(self):
        proc = run_cli(
            "--engine",
            "/nonexistent-dir/fyrn --model {model} --prompt {prompt}",
            "--models", "alpha")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot find the engine command", proc.stderr)
        self.assertIn("/nonexistent-dir/fyrn", proc.stderr)

    def test_existing_command_passes_guard(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha", "--dry-run")
        self.assertEqual(proc.returncode, 0)

    def test_shell_builtin_first_token_skips_check(self):
        # echo is a shell builtin: no file to check, and it replies.
        proc = run_cli("--engine", "echo {model} {prompt}",
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("alpha: PASS", proc.stdout)


class TestRunVerdicts(unittest.TestCase):

    def test_reply_mode_all_pass(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha", "beta")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("alpha: PASS", proc.stdout)
        self.assertIn("beta: PASS", proc.stdout)
        self.assertIn("Summary: 2 of 2 models passed", proc.stdout)
        self.assertIn("Mock reply from alpha", proc.stdout)

    def test_hang_mode_timeout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            prompts = write_lines(tmp, "p.txt", ["hello"])
            started = time.monotonic()
            proc = run_cli("--engine", mock_template("hang"),
                           "--models", "alpha", "--prompts", prompts,
                           "--timeout", "2")
            elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alpha: TIMEOUT", proc.stdout)
        self.assertIn("timed out after 2 seconds", proc.stdout)
        # The mock sleeps an hour: a fast return proves the kill.
        self.assertLess(elapsed, 10.0)

    def test_error_mode(self):
        proc = run_cli("--engine", mock_template("error"),
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alpha: ERROR", proc.stdout)
        self.assertIn("exited with code 1", proc.stdout)
        self.assertIn("mock engine failed on purpose", proc.stdout)

    def test_empty_mode(self):
        proc = run_cli("--engine", mock_template("empty"),
                       "--models", "alpha")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alpha: EMPTY", proc.stdout)
        self.assertIn("reply was empty", proc.stdout)

    def test_auto_mode_mixed_verdicts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            prompts = write_lines(tmp, "p.txt", ["hello"])
            proc = run_cli("--engine", mock_template("auto"),
                           "--models", "good", "bad-hang", "bad-error",
                           "bad-empty", "--prompts", prompts,
                           "--timeout", "5")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("good: PASS", proc.stdout)
        self.assertIn("bad-hang: TIMEOUT", proc.stdout)
        self.assertIn("bad-error: ERROR", proc.stdout)
        self.assertIn("bad-empty: EMPTY", proc.stdout)
        self.assertIn("Summary: 1 of 4 models passed", proc.stdout)

    def test_slow_reply_passes(self):
        proc = run_cli("--engine", mock_template("reply", "--delay 1"),
                       "--models", "alpha", "--timeout", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("alpha: PASS", proc.stdout)


class TestVerdictPrecedence(unittest.TestCase):
    """Worst verdict wins: timeout beats error beats empty beats pass."""

    def test_timeout_beats_error(self):
        report = mcs.run_smoke_test(
            mock_template("auto"), ["alpha"],
            ["say hi HANG", "say hi ERROR"], 5)
        self.assertEqual(report["models"][0]["verdict"], "timeout")

    def test_error_beats_empty(self):
        report = mcs.run_smoke_test(
            mock_template("auto"), ["alpha"],
            ["say hi ERROR", "say hi EMPTY"], 5)
        self.assertEqual(report["models"][0]["verdict"], "error")

    def test_empty_beats_pass(self):
        report = mcs.run_smoke_test(
            mock_template("auto"), ["alpha"],
            ["say hi", "say hi EMPTY"], 5)
        self.assertEqual(report["models"][0]["verdict"], "empty")


class TestJsonReport(unittest.TestCase):

    def test_format_json_parses(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha", "--format", "json")
        self.assertEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        self.assertEqual(report["tool"], "model-chat-smoke-test")
        self.assertEqual(report["version"], "0.1.0")
        self.assertEqual(report["summary"],
                         {"total": 1, "passed": 1, "failed": 0})
        self.assertEqual(len(report["models"][0]["prompts"]), 3)
        self.assertEqual(report["models"][0]["prompts"][0]["verdict"],
                         "pass")

    def test_json_file_written_and_stdout_stays_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            proc = run_cli("--engine", mock_template("reply"),
                           "--models", "alpha", "--json", out)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("alpha: PASS", proc.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["passed"], 1)

    def test_json_file_unwritable(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha",
                       "--json", "/nonexistent-dir-xyz/report.json")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot write the JSON report", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestInputs(unittest.TestCase):

    def test_models_file_parsing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            models = write_lines(tmp, "m.txt",
                                 ["alpha", "# comment", "", "beta"])
            proc = run_cli("--engine", mock_template("reply"),
                           "--models-file", models)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Summary: 2 of 2 models passed", proc.stdout)

    def test_models_file_missing(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models-file", "no-such-models.txt")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)

    def test_models_file_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            models = write_lines(tmp, "m.txt", ["# only a comment", ""])
            proc = run_cli("--engine", mock_template("reply"),
                           "--models-file", models)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("has no models in it", proc.stderr)

    def test_models_and_models_file_together(self):
        proc = run_cli("--engine", mock_template("reply"),
                       "--models", "alpha",
                       "--models-file", "models.txt")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not both", proc.stderr)

    def test_prompts_file_parsing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            prompts = write_lines(tmp, "p.txt",
                                  ["one", "# comment", "", "two"])
            proc = run_cli("--engine", mock_template("reply"),
                           "--models", "alpha", "--prompts", prompts,
                           "--dry-run")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(proc.stdout.strip().split("\n")), 2)

    def test_bad_timeout(self):
        for bad in ("0", "-5"):
            with self.subTest(timeout=bad):
                proc = run_cli("--engine", mock_template("reply"),
                               "--models", "alpha", "--timeout", bad)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("--timeout must be above 0", proc.stderr)


class TestDebugReport(unittest.TestCase):

    def test_debug_report_writes_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_cli("--debug-report", cwd=tmp)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("Debug report written to", proc.stdout)
            reports = list(Path(tmp).rglob("debug-report-*.txt"))
            self.assertEqual(len(reports), 1)

    def test_debug_log_unmodified(self):
        digest = hashlib.sha256(
            (TOOL_DIR / "debug_log.py").read_bytes()).hexdigest()
        self.assertEqual(digest, DEBUG_LOG_SHA)


class TestTreeHygiene(unittest.TestCase):

    def test_no_em_dash_in_output(self):
        """No em-dash in what the user sees: the report on stdout,
        and the error text on stderr."""
        dash = chr(0x2014)
        passed = run_cli("--engine", mock_template("reply"),
                         "--models", "alpha")
        self.assertNotIn(dash, passed.stdout)
        failed = run_cli("--engine", mock_template("error"),
                         "--models", "alpha")
        self.assertNotIn(dash, failed.stdout)
        missing = run_cli(
            "--engine",
            "no-such-engine-xyz-12345 --model {model} --prompt {prompt}",
            "--models", "alpha")
        self.assertNotIn(dash, missing.stderr)

    def test_no_em_dash_in_docs(self):
        """No em-dash in this tool's own files (docs, scripts, the
        CLI, the desktop files). debug_log.py is excluded on purpose:
        it is the verbatim T21 copy and its own text holds em-dashes;
        editing it would break the hash pin, so it is out of scope."""
        dash = chr(0x2014)
        escape = "\\" + "u2014"  # built from parts: the literal
        # sequence must not appear in this file, or the scan trips
        # on itself.
        names = ["README.md", "CHANGELOG.md", "BUILD_REPORT.md",
                 "model_chat_smoke_test.py", "build_zip.py",
                 "run_tests.sh", "install.sh", "uninstall.sh",
                 "show-help.sh",
                 "Install Model Chat Smoke Test.desktop",
                 "model-chat-smoke-test.desktop",
                 "tests/test_model_chat_smoke_test.py",
                 "tests/mock_engine.py"]
        for name in names:
            path = TOOL_DIR / name
            self.assertTrue(path.is_file(), "missing file: %s" % name)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(dash, text, "em-dash in %s" % name)
            self.assertNotIn(escape, text, "em-dash escape in %s" % name)

    def test_installer_desktop_exec_matches_fixed_template(self):
        """The S6 empty-%k fix, pinned: the installer Exec must be the
        fixed template line, byte for byte."""
        desktop = TOOL_DIR / "Install Model Chat Smoke Test.desktop"
        exec_lines = [line for line in
                      desktop.read_text(encoding="utf-8").splitlines()
                      if line.startswith("Exec=")]
        self.assertEqual(len(exec_lines), 1)
        self.assertEqual(exec_lines[0], FIXED_EXEC)

    def test_version_agrees_with_changelog(self):
        changelog = (TOOL_DIR / "CHANGELOG.md").read_text(
            encoding="utf-8")
        self.assertIn("## v%s" % mcs.VERSION, changelog)


class TestUnitFunctions(unittest.TestCase):

    def test_build_command_quotes(self):
        command = mcs.build_command(
            "eng --model {model} --prompt {prompt}",
            "my model", 'say "hi"')
        self.assertEqual(
            command,
            "eng --model 'my model' --prompt 'say \"hi\"'")

    def test_one_line_truncates(self):
        long_reply = "word " * 100
        preview = mcs._one_line(long_reply, 200)
        self.assertLessEqual(len(preview), 203)
        self.assertTrue(preview.endswith("..."))
        self.assertNotIn("\n", preview)

    def test_check_engine_command_returns_name(self):
        self.assertEqual(mcs.check_engine_command("python3 -u x.py"),
                         "python3")


if __name__ == "__main__":
    unittest.main()
