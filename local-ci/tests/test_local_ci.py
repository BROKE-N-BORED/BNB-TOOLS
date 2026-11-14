"""Tests for local_ci.py (BNB-TOOLS T28).

Fixture repos are built in temp dirs; nothing touches a live
repo. The suite subprocess runs are real (a passing suite, a
failing suite, a sleeping suite for the timeout) so the gate is
proven end to end, not just mocked.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)

import local_ci  # noqa: E402

PASSING_TEST = '''import unittest


class GreenTests(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1 + 1, 2)

    def test_two(self):
        self.assertTrue(True)
'''

FAILING_TEST = '''import unittest


class RedTests(unittest.TestCase):
    def test_passes(self):
        self.assertEqual(1, 1)

    def test_fails(self):
        self.assertEqual(1, 2)
'''


def write_file(root, rel, content, executable=False):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    if executable:
        os.chmod(path, 0o755)
    return path


class CiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="local-ci-test.")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        # Keep throwaway work inside the test temp dir.
        self.old_tmp = os.environ.get("LOCAL_CI_TMP")
        os.environ["LOCAL_CI_TMP"] = os.path.join(self.tmp, "work")
        os.makedirs(os.environ["LOCAL_CI_TMP"])

    def tearDown(self):
        if self.old_tmp is None:
            os.environ.pop("LOCAL_CI_TMP", None)
        else:
            os.environ["LOCAL_CI_TMP"] = self.old_tmp
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, config):
        write_file(self.repo, "ci/config.json",
                   json.dumps(config, indent=2) + "\n")

    def run_check(self, extra_args=None):
        """Run the check in-process; returns (exit, stdout, stderr)."""
        argv = ["check", "--repo", self.repo] + (extra_args or [])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = local_ci.main(argv)
        return code, out.getvalue(), err.getvalue()

    def verdict(self, name="CI-STATUS.md"):
        path = os.path.join(self.repo, name)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def green_repo(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "tests/test_green.py", PASSING_TEST)
        write_file(self.repo, "install.sh", "#!/bin/sh\necho hi\n",
                   executable=True)
        return self.repo


class HelpTests(CiTestCase):
    def run_cli(self, argv):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(TOOL_DIR, "local_ci.py")] + argv,
            capture_output=True, text=True, timeout=30)
        return proc

    def test_help(self):
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("pre-push check", proc.stdout)
        self.assertIn("check", proc.stdout)
        self.assertIn("setup", proc.stdout)

    def test_short_help(self):
        proc = self.run_cli(["-h"])
        self.assertEqual(proc.returncode, 0)

    def test_check_help(self):
        proc = self.run_cli(["check", "--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--repo", proc.stdout)
        self.assertIn("--no-status", proc.stdout)

    def test_setup_help(self):
        proc = self.run_cli(["setup", "--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--force", proc.stdout)

    def test_version(self):
        proc = self.run_cli(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(local_ci.VERSION, proc.stdout)

    def test_no_args_prints_usage_and_exits_2(self):
        proc = self.run_cli([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("pre-push check", proc.stdout)


class ConfigTests(CiTestCase):
    def test_missing_config_degrades_to_defaults_with_message(self):
        self.green_repo()
        code, out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("no ci/config.json found, using defaults", out)
        self.assertIn("2 checks - PASS", out)

    def test_overrides_applied(self):
        self.green_repo()
        self.write_config({"project": "My Cool Project",
                           "status_file": "STATUS2.md",
                           "zip_top": "cool-top"})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIsNone(self.verdict("CI-STATUS.md"))
        text = self.verdict("STATUS2.md")
        self.assertIsNotNone(text)
        self.assertIn("# My Cool Project CI status", text)

    def test_unknown_key_is_an_error_with_red_verdict(self):
        self.green_repo()
        self.write_config({"suit_command": ["python3", "-m", "unittest"]})
        code, _out, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("suit_command", err)
        text = self.verdict()
        self.assertIsNotNone(text)
        self.assertIn("Verdict: FAIL", text)
        self.assertIn("suit_command", text)

    def test_broken_json_is_an_error_with_red_verdict(self):
        self.green_repo()
        write_file(self.repo, "ci/config.json", "{not json")
        code, _out, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("cannot read config", err)
        self.assertIn("Verdict: FAIL", self.verdict())

    def test_underscore_keys_are_ignored_comments(self):
        self.green_repo()
        self.write_config({"_comment": "starter config, edit me",
                           "_note": "anything starting with _ is fine"})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)

    def test_string_suite_command_is_split(self):
        self.green_repo()
        self.write_config(
            {"suite_command": "python3 -m unittest discover -s tests"})
        code, out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("2 checks - PASS", out)

    def test_repo_that_is_not_a_dir_exits_2(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = local_ci.main(["check", "--repo",
                                  os.path.join(self.tmp, "nope")])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err.getvalue())


class SuiteCheckTests(CiTestCase):
    def test_passing_suite_reports_count(self):
        self.green_repo()
        code, out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Suite: 2 checks - PASS", self.verdict())
        self.assertIn("CI PASS", out)

    def test_failing_suite_is_red_and_names_the_failure(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "tests/test_red.py", FAILING_TEST)
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("FAIL: test_fails", out)
        text = self.verdict()
        self.assertIn("Verdict: FAIL", text)
        self.assertIn("Suite: 2 checks - FAIL", text)

    def test_no_tests_dir_skips_suite(self):
        write_file(self.repo, "README.md", "# No tests here\n")
        code, out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("no tests/ dir and no suite_command", out)
        self.assertIn("Suite: SKIP", self.verdict())

    def test_timeout_fails(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        self.write_config({
            "suite_command": [sys.executable, "-c",
                              "import time; time.sleep(10)"],
            "suite_timeout": 2})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("timed out after 2s", out)
        self.assertIn("Suite: FAIL, timed out", self.verdict())

    def test_command_not_found_fails(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        self.write_config({"suite_command": ["no-such-command-xyz"]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("suite command not found", out)


class ZipCheckTests(CiTestCase):
    def test_zip_counts_and_modes(self):
        self.green_repo()
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        text = self.verdict()
        # README + test file + install.sh = 3 files, 1 dir (tests).
        self.assertIn("Release zip: OK: 3 files, 1 dirs", text)
        self.assertIn("modes verified, SHA-256 ", text)

    def test_nested_zip_excluded_by_default(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        with open(os.path.join(self.repo, "inner.zip"), "wb") as handle:
            handle.write(b"PK\x03\x04" + b"x" * 100)
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Release zip: OK: 1 files, 0 dirs", self.verdict())

    def test_zip_disabled_skips(self):
        self.green_repo()
        self.write_config({"zip": False})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Release zip: SKIP", self.verdict())

    def test_missing_manifest_fails_zip_and_modes(self):
        self.green_repo()
        self.write_config({"zip_executables_file": "EXECUTABLES.txt"})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("missing manifest", out)

    def test_verify_rejects_wrong_stored_mode(self):
        bad_zip = os.path.join(self.tmp, "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            info = zipfile.ZipInfo("top/install.sh")
            info.create_system = 3
            info.external_attr = 0o100644 << 16  # wrong: not executable
            zf.writestr(info, b"#!/bin/sh\n")
        with self.assertRaises(ValueError) as ctx:
            local_ci.verify_zip(bad_zip, {"install.sh"}, [], "top")
        self.assertIn("install.sh", str(ctx.exception))
        self.assertIn("100644", str(ctx.exception))

    def test_verify_accepts_right_stored_mode(self):
        good_zip = os.path.join(self.tmp, "good.zip")
        with zipfile.ZipFile(good_zip, "w") as zf:
            info = zipfile.ZipInfo("top/install.sh")
            info.create_system = 3
            info.external_attr = 0o100755 << 16
            zf.writestr(info, b"#!/bin/sh\n")
            info = zipfile.ZipInfo("top/README.md")
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zf.writestr(info, b"# hi\n")
        # No exception means the verify passed.
        local_ci.verify_zip(good_zip, {"install.sh"}, [], "top")


class ModeCheckTests(CiTestCase):
    def test_listed_executable_without_exec_bit_is_red(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "install.sh", "#!/bin/sh\necho hi\n",
                   executable=False)
        self.write_config({"zip_executables": ["install.sh"]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("not executable on disk: install.sh", out)
        self.assertIn("Modes: FAIL", self.verdict())

    def test_listed_executable_missing_is_red(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        self.write_config({"zip_executables": ["install.sh"]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("listed executable missing: install.sh", out)

    def test_default_list_missing_names_are_fine(self):
        # No scripts at all: the default list is candidates, not
        # requirements, so the mode check passes with 0 checked.
        write_file(self.repo, "README.md", "# Fixture\n")
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Modes: 0 executables on disk OK - PASS",
                      self.verdict())

    def test_default_list_present_but_not_executable_is_red(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "run.sh", "#!/bin/sh\necho hi\n",
                   executable=False)
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("not executable on disk: run.sh", out)

    def test_glob_matched_script_needs_no_exec_bit(self):
        # A *.sh invoked only via `sh file.sh` is fine without
        # +x: the zip still stores it 100755.
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "helper.sh", "echo hi\n", executable=False)
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)

    def test_manifest_names_are_required(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "EXECUTABLES.txt",
                   "# comment\nlaunch.sh\n")
        write_file(self.repo, "launch.sh", "#!/bin/sh\n",
                   executable=True)
        self.write_config(
            {"zip_executables_file": "EXECUTABLES.txt"})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("1 executables on disk OK - PASS", self.verdict())

    def test_mode_check_disabled_skips(self):
        write_file(self.repo, "README.md", "# Fixture\n")
        write_file(self.repo, "install.sh", "#!/bin/sh\n",
                   executable=False)
        self.write_config({"zip_executables": ["install.sh"],
                           "mode_check": False})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Modes: SKIP", self.verdict())


class DocCountTests(CiTestCase):
    def setUp(self):
        super().setUp()
        write_file(self.repo, "README.md",
                   "# Fixture\n72 skills in the library\n"
                   "72 skills and counting\nline four\nline five\n")
        for name in ("alpha", "beta", "gamma"):
            write_file(self.repo, f"skills/{name}/SKILL.md", "# S\n")
        write_file(self.repo, "tests/test_a.py", PASSING_TEST)
        write_file(self.repo, "tests/test_b.py", PASSING_TEST)
        write_file(self.repo, "tests/helper.py", "# helper\n")

    def test_all_kinds(self):
        self.write_config({"doc_counts": [
            {"label": "skills", "kind": "dirs", "path": "skills",
             "expected": 3},
            {"label": "test files", "kind": "files", "path": "tests",
             "pattern": "test_*.py", "expected": 2},
            {"label": "readme lines", "kind": "lines", "path": "README.md",
             "expected": 5},
            {"label": "skill mentions", "kind": "matches",
             "path": "README.md", "pattern": "72 skills",
             "expected": 2},
        ]})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        text = self.verdict()
        self.assertIn("skills: 3 (expected 3) - PASS", text)
        self.assertIn("test files: 2 (expected 2) - PASS", text)
        self.assertIn("readme lines: 5 (expected 5) - PASS", text)
        self.assertIn("skill mentions: 2 (expected 2) - PASS", text)

    def test_expected_mismatch_is_red(self):
        self.write_config({"doc_counts": [
            {"label": "skills", "kind": "dirs", "path": "skills",
             "expected": 99}]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("skills: 3 (expected 99) - FAIL", out)
        self.assertIn("skills: 3 (expected 99) - FAIL", self.verdict())

    def test_min_max(self):
        self.write_config({"doc_counts": [
            {"label": "skills", "kind": "dirs", "path": "skills",
             "min": 2, "max": 5}]})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("skills: 3 (min 2, max 5) - PASS", self.verdict())

    def test_min_violation_is_red(self):
        self.write_config({"doc_counts": [
            {"label": "skills", "kind": "dirs", "path": "skills",
             "min": 4}]})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 1)

    def test_count_without_assertion_is_recorded_only(self):
        self.write_config({"doc_counts": [
            {"label": "skills", "kind": "dirs", "path": "skills"}]})
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("skills: 3 - PASS", self.verdict())

    def test_missing_path_is_red(self):
        self.write_config({"doc_counts": [
            {"label": "nope", "kind": "dirs", "path": "missing"}]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("path not found: missing", out)

    def test_unknown_kind_is_red(self):
        self.write_config({"doc_counts": [
            {"label": "weird", "kind": "widgets", "path": "skills"}]})
        code, out, _err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("unknown kind", out)


class VerdictTests(CiTestCase):
    def test_green_verdict_shape(self):
        self.green_repo()
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        text = self.verdict()
        self.assertIn("# repo CI status", text)
        self.assertIn("Free CI (`ci/check.sh`)", text)
        self.assertIn("- Commit: unknown (not a git checkout)", text)
        self.assertIn("- Date (UTC): 20", text)
        self.assertIn("- Verdict: PASS", text)
        self.assertIn("- Suite: 2 checks - PASS", text)
        self.assertIn("- Release zip: OK:", text)
        self.assertIn("- Modes: 1 executables on disk OK - PASS", text)
        self.assertIn("- Repo: 3 files,", text)
        self.assertIn("- Total: ", text)
        self.assertIn("Run `sh ci/check.sh`", text)

    def test_no_em_dash_anywhere_in_verdict(self):
        self.green_repo()
        self.run_check()
        self.assertNotIn("\u2014", self.verdict())

    def test_no_status_flag_writes_nothing(self):
        self.green_repo()
        code, out, _err = self.run_check(["--no-status"])
        self.assertEqual(code, 0)
        self.assertIsNone(self.verdict())
        self.assertIn("CI PASS", out)

    def test_git_commit_recorded(self):
        self.green_repo()
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="Test",
                   GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q"], cwd=self.repo,
                       env=env, check=True, timeout=30)
        subprocess.run(["git", "add", "-A"], cwd=self.repo,
                       env=env, check=True, timeout=30)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"],
                       cwd=self.repo, env=env, check=True, timeout=30)
        short = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=self.repo,
            capture_output=True, text=True, check=True,
            timeout=30).stdout.strip()
        code, _out, _err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn(f"- Commit: {short}", self.verdict())


class SetupTests(CiTestCase):
    def run_setup(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = local_ci.main(["setup"] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_installs_three_files(self):
        self.green_repo()
        code, out, _err = self.run_setup(self.repo)
        self.assertEqual(code, 0)
        self.assertIn("installed local CI", out)
        script = os.path.join(self.repo, "ci", "local_ci.py")
        wrapper = os.path.join(self.repo, "ci", "check.sh")
        config = os.path.join(self.repo, "ci", "config.json")
        for path in (script, wrapper, config):
            self.assertTrue(os.path.isfile(path), path)
        self.assertTrue(os.stat(script).st_mode & stat.S_IXUSR)
        self.assertTrue(os.stat(wrapper).st_mode & stat.S_IXUSR)
        with open(wrapper, encoding="utf-8") as handle:
            self.assertIn("local_ci.py", handle.read())
        with open(config, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["project"], "repo")
        self.assertEqual(data["suite_command"],
                         local_ci.DEFAULT_SUITE_COMMAND)

    def test_refuses_overwrite_without_force(self):
        self.green_repo()
        self.assertEqual(self.run_setup(self.repo)[0], 0)
        code, _out, err = self.run_setup(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("already installed", err)

    def test_force_overwrites(self):
        self.green_repo()
        self.assertEqual(self.run_setup(self.repo)[0], 0)
        code, _out, _err = self.run_setup(self.repo, "--force")
        self.assertEqual(code, 0)

    def test_project_flag(self):
        self.green_repo()
        code, _out, _err = self.run_setup(self.repo, "--project",
                                          "Named Project")
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, "ci", "config.json"),
                  encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["project"],
                             "Named Project")

    def test_manifest_detected_in_starter_config(self):
        self.green_repo()
        write_file(self.repo, "EXECUTABLES.txt", "install.sh\n")
        code, _out, _err = self.run_setup(self.repo)
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, "ci", "config.json"),
                  encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["zip_executables_file"],
                         "EXECUTABLES.txt")

    def test_no_tests_dir_omits_suite_command(self):
        write_file(self.repo, "README.md", "# No tests\n")
        code, _out, _err = self.run_setup(self.repo)
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, "ci", "config.json"),
                  encoding="utf-8") as handle:
            self.assertNotIn("suite_command", json.load(handle))

    def test_setup_target_must_be_a_dir(self):
        code, _out, err = self.run_setup(os.path.join(self.tmp, "nope"))
        self.assertEqual(code, 1)
        self.assertIn("not a directory", err)

    def test_installed_check_runs_green_via_sh(self):
        # The J1 invocation shape: `sh ci/check.sh` from the repo.
        self.green_repo()
        self.assertEqual(self.run_setup(self.repo)[0], 0)
        proc = subprocess.run(
            ["sh", "ci/check.sh"], cwd=self.repo,
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ,
                     LOCAL_CI_TMP=os.path.join(self.tmp, "work2")))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("CI PASS", proc.stdout)
        self.assertIn("Verdict: PASS", self.verdict())


if __name__ == "__main__":
    unittest.main()
