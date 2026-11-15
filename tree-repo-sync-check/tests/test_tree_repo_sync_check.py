"""Tests for tree-repo-sync-check (BNB-TOOLS T33).

Every network test runs against the local fake GitHub server in
helpers.py. No test touches the live network or the live plugins
repo. The coordinator runs a live check at ship time.

Coverage: help/version, bad input, clean/differing/missing
buckets (including the BNB-PLUGINS worked example shape), JSON
output, branch handling, 404/403/500/truncated/bad-JSON/no-tree
failures, rate limits (reset time named, exactly one request, no
retry), no-network, no Authorization header, .git skipping,
symlinks, submodule entries, binary files, the blob SHA against
real git hash-object, the debug log wiring, and the zip modes.
"""

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402
from helpers import (FAKE_GITHUB, FIXED_RESET_TEXT,  # noqa: E402
                     make_repo_fixtures, start_fake_github,
                     stop_fake_github, tree_from_files)
from tree_repo_sync_check import blob_sha, collect_local, compare  # noqa: E402
from debug_log import DebugLogger  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(TREE, "tree_repo_sync_check.py")
EM_DASH = "\u2014"
EXPECTED_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")
REPO = "TEST-ORG/test-repo"


def run_tool(args, cwd=None, env_extra=None):
    """Run the tool as a subprocess. Returns the CompletedProcess.

    TREE_SYNC_API_BASE is stripped unless the test sets it, so
    one test's environment cannot leak into another.
    """
    env = dict(os.environ)
    env.pop("TREE_SYNC_API_BASE", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, timeout=60, cwd=cwd, env=env)


def write_local(root, mapping):
    """Write {relative path: bytes or str} under root."""
    for rel, content in mapping.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(content)


@contextlib.contextmanager
def fake_server(fixtures):
    server, base_url = start_fake_github(fixtures)
    try:
        yield server, base_url
    finally:
        stop_fake_github(server)


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        handler.close()
        logger.logger.removeHandler(handler)


# ---------------------------------------------------------------- units

class UnitTests(unittest.TestCase):
    def test_blob_sha_matches_the_git_formula(self):
        data = b"hello world\n"
        expect = hashlib.sha1(b"blob %d\0" % len(data) + data)
        self.assertEqual(blob_sha(data), expect.hexdigest())

    def test_blob_sha_differs_for_different_content(self):
        self.assertNotEqual(blob_sha(b"one"), blob_sha(b"two"))
        self.assertEqual(blob_sha(b"same"), blob_sha(b"same"))

    def test_blob_sha_matches_git_hash_object(self):
        git = shutil.which("git")
        if git is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.txt")
            with open(path, "wb") as handle:
                handle.write(b"the quick brown fox\n")
            proc = subprocess.run(
                [git, "hash-object", path],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(blob_sha(b"the quick brown fox\n"),
                             proc.stdout.strip())

    def test_compare_splits_into_three_buckets(self):
        local = {"same.py": "a", "diff.py": "b", "local-only.py": "c"}
        remote = {"same.py": "a", "diff.py": "z",
                  "remote-only.py": "d"}
        differing, missing_on_remote, missing_locally = compare(
            local, remote)
        self.assertEqual(differing, ["diff.py"])
        self.assertEqual(missing_on_remote, ["local-only.py"])
        self.assertEqual(missing_locally, ["remote-only.py"])

    def test_collect_local_skips_git_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "a",
                              ".git/config": "junk",
                              "sub/.git/objects/x": "junk"})
            found = collect_local(tmp)
            self.assertEqual(sorted(found), ["a.py"])

    def test_collect_local_hashes_a_symlink_by_its_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"real.txt": "real content"})
            os.symlink("real.txt", os.path.join(tmp, "link.txt"))
            found = collect_local(tmp)
            self.assertEqual(found["link.txt"],
                             blob_sha(b"real.txt"))


# ---------------------------------------------------------------- CLI

class CliTests(unittest.TestCase):
    def test_help_exits_zero_and_names_public_repos(self):
        proc = run_tool(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Public repos only", proc.stdout)
        self.assertNotIn(EM_DASH, proc.stdout)

    def test_version_exits_zero(self):
        proc = run_tool(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0.1.0", proc.stdout)

    def test_debug_report_help_exits_zero(self):
        proc = run_tool(["debug-report", "--help"])
        self.assertEqual(proc.returncode, 0)

    def test_no_args_exits_two_without_traceback(self):
        proc = run_tool([])
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_bad_repo_format_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_tool([tmp, "noslash"])
            self.assertEqual(proc.returncode, 2)
            self.assertIn("owner/repo", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_missing_local_dir_exits_two(self):
        missing = os.path.join(tempfile.gettempdir(),
                               "tree-sync-no-such-dir-xyz")
        proc = run_tool([missing, REPO])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_plain_system_python3_runs_help(self):
        python3 = shutil.which("python3")
        if python3 is None:
            self.skipTest("no system python3 on PATH")
        proc = subprocess.run(
            [python3, SCRIPT, "--help"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)


# ---------------------------------------------------------------- sync

class SyncTests(unittest.TestCase):
    def _fixtures(self, tree, **extra):
        fixture = {"tree": tree}
        fixture.update(extra)
        return make_repo_fixtures({REPO: fixture})

    def test_clean_repo_exits_zero(self):
        files = {"a.py": "print(1)\n", "sub/b.py": "print(2)\n"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            fixtures = self._fixtures(tree_from_files(files))
            with fake_server(fixtures) as (_srv, base_url):
                proc = run_tool([tmp, REPO, "--api-base", base_url])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("OK: local tree matches the remote tree "
                      "(2 files).", proc.stdout)
        self.assertNotIn(EM_DASH, proc.stdout)

    def test_differing_file_exits_one_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "fixed content\n"})
            remote = tree_from_files({"a.py": "broken content\n"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Differing (1):", proc.stdout)
        self.assertIn("  a.py", proc.stdout)

    def test_bnb_plugins_case_names_both_plugin_files(self):
        """The worked example: the local tree fixed two live
        defects in github/plugin.py and huggingface/plugin.py
        and the repo never re-synced, so both files differ."""
        local = {"github/plugin.py": "fixed github\n",
                 "huggingface/plugin.py": "fixed huggingface\n",
                 "README.md": "same\n"}
        remote = tree_from_files(
            {"github/plugin.py": "broken github\n",
             "huggingface/plugin.py": "broken huggingface\n",
             "README.md": "same\n"})
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, local)
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("  github/plugin.py", proc.stdout)
        self.assertIn("  huggingface/plugin.py", proc.stdout)
        self.assertNotIn("README.md", proc.stdout)

    def test_missing_on_remote_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "a", "notes.txt": "local only"})
            remote = tree_from_files({"a.py": "a"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Missing on remote (extra local files) (1):",
                      proc.stdout)
        self.assertIn("  notes.txt", proc.stdout)

    def test_missing_locally_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "a"})
            remote = tree_from_files({"a.py": "a", "old.py": "gone"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Missing locally (only on remote) (1):",
                      proc.stdout)
        self.assertIn("  old.py", proc.stdout)

    def test_all_three_buckets_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"diff.py": "new", "local.py": "x"})
            remote = tree_from_files({"diff.py": "old",
                                      "gone.py": "y"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("1 differing, 1 missing on remote, "
                      "1 missing locally.", proc.stdout)

    def test_json_clean_output_shape(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            fixtures = self._fixtures(tree_from_files(files))
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--json"])
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "clean")
        self.assertEqual(result["repo"], REPO)
        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["remote_files"], 1)
        self.assertEqual(result["local_files"], 1)
        self.assertEqual(result["differing"], [])
        self.assertEqual(result["missing_on_remote"], [])
        self.assertEqual(result["missing_locally"], [])

    def test_json_differences_output_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "new", "local.py": "x"})
            remote = tree_from_files({"a.py": "old"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--json"])
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "differences")
        self.assertEqual(result["differing"], ["a.py"])
        self.assertEqual(result["missing_on_remote"], ["local.py"])
        self.assertEqual(result["missing_locally"], [])

    def test_json_error_output_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = make_repo_fixtures({})
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--json"])
        self.assertEqual(proc.returncode, 2)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["error"])
        self.assertIsNone(result["rate_limit_reset"])
        self.assertEqual(proc.stderr, "")

    def test_branch_flag_is_honored(self):
        branches = {"main": tree_from_files({"a.py": "main"}),
                    "dev": tree_from_files({"a.py": "dev"})}
        fixtures = make_repo_fixtures(
            {REPO: {"branches": branches}})
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "dev"})
            with fake_server(fixtures) as (srv, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--branch", "dev"])
                paths = [p for (_m, p, _h)
                         in srv.fake_state.recorded_requests]
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(any("/git/trees/dev" in p for p in paths))

    def test_unknown_branch_is_a_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures(tree_from_files({}))
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--branch", "nope"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)

    def test_repo_404_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = make_repo_fixtures({})
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)
        self.assertIn(REPO, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_rate_limit_exits_two_names_reset_and_makes_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="rate_limit")
            with fake_server(fixtures) as (srv, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
                total = srv.fake_state.total_requests()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("rate limit", proc.stderr)
        self.assertIn(FIXED_RESET_TEXT, proc.stderr)
        self.assertIn("No retry was made", proc.stderr)
        self.assertEqual(total, 1, "rate limit must never retry")

    def test_rate_limit_without_reset_header_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="rate_limit_no_reset")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("rate limit", proc.stderr)
        self.assertIn("did not give a reset time", proc.stderr)

    def test_forbidden_mentions_public_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="forbidden")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("public repos", proc.stderr)
        self.assertNotIn("rate limit", proc.stderr)

    def test_server_error_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="error")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("HTTP 500", proc.stderr)

    def test_truncated_tree_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="truncated")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("truncated", proc.stderr)

    def test_bad_json_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="bad_json")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stderr)

    def test_reply_without_a_tree_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures({}, mode="no_tree")
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no tree", proc.stderr)

    def test_no_network_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, base_url = start_fake_github(
                make_repo_fixtures({}))
            stop_fake_github(server)
            proc = run_tool([tmp, REPO, "--api-base", base_url])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("could not reach GitHub", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_no_authorization_header_is_sent(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            fixtures = self._fixtures(tree_from_files(files))
            with fake_server(fixtures) as (srv, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(srv.fake_state.recorded_requests)
        for (_method, _path, headers) in \
                srv.fake_state.recorded_requests:
            self.assertNotIn("authorization", headers)

    def test_env_var_api_base_is_honored(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            fixtures = self._fixtures(tree_from_files(files))
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO],
                                env_extra={"TREE_SYNC_API_BASE": url})
        self.assertEqual(proc.returncode, 0)

    def test_git_dir_contents_do_not_count_as_drift(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            write_local(tmp, {".git/config": "junk",
                              ".git/refs/heads/main": "junk"})
            fixtures = self._fixtures(tree_from_files(files))
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 0)

    def test_submodule_and_tree_entries_are_ignored(self):
        files = {"a.py": "a"}
        extra = [{"path": "vendor/lib", "type": "commit",
                  "sha": "1" * 40},
                 {"path": "sub", "type": "tree", "sha": "2" * 40}]
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            fixtures = self._fixtures(tree_from_files(files),
                                      extra_entries=extra)
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 0)

    def test_empty_local_and_empty_remote_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._fixtures(tree_from_files({}))
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("(0 files)", proc.stdout)

    def test_binary_file_difference_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"blob.bin": b"\x00\x01\x02\x03"})
            remote = tree_from_files({"blob.bin": b"\x00\x01\x02\x04"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("  blob.bin", proc.stdout)

    def test_difference_output_has_no_em_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, {"a.py": "new"})
            remote = tree_from_files({"a.py": "old"})
            with fake_server(self._fixtures(remote)) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url])
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn(EM_DASH, proc.stdout)


# ---------------------------------------------------------------- debug

class DebugTests(unittest.TestCase):
    def test_debug_log_module_is_the_verbatim_layer(self):
        path = os.path.join(TREE, "debug_log.py")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_DEBUG_LOG_SHA256)

    def test_debug_report_flag_writes_a_report(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            report = os.path.join(tmp, "report.txt")
            fixtures = make_repo_fixtures(
                {REPO: {"tree": tree_from_files(files)}})
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--debug-report", report])
            self.assertEqual(proc.returncode, 0)
            self.assertIn("debug report written to", proc.stderr)
            text = Path(report).read_text(encoding="utf-8")
            self.assertIn("tree-repo-sync-check", text)
            self.assertIn("0.1.0", text)

    def test_debug_report_flag_keeps_json_stdout_clean(self):
        files = {"a.py": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            write_local(tmp, files)
            report = os.path.join(tmp, "report.txt")
            fixtures = make_repo_fixtures(
                {REPO: {"tree": tree_from_files(files)}})
            with fake_server(fixtures) as (_s, url):
                proc = run_tool([tmp, REPO, "--api-base", url,
                                 "--json", "--debug-report", report])
            self.assertEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "clean")
            self.assertTrue(os.path.isfile(report))

    def test_debug_report_subcommand_writes_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.txt")
            fixtures = make_repo_fixtures({})
            with fake_server(fixtures) as (_s, url):
                proc = run_tool(["debug-report", "--out", report,
                                 "--api-base", url], cwd=tmp)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("Debug report written to", proc.stdout)
            text = Path(report).read_text(encoding="utf-8")
            self.assertIn("tree-repo-sync-check", text)
            self.assertIn("GitHub API", text)

    def test_fake_secret_is_scrubbed_from_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = os.path.join(tmp, "logs")
            logger = DebugLogger("tree-repo-sync-check", "0.1.0",
                                 log_dir=log_dir)
            try:
                logger.action("saw token %s" % FAKE_GITHUB)
                report = logger.generate_report(
                    os.path.join(tmp, "report.txt"))
            finally:
                _close_logger(logger)
            text = Path(report).read_text(encoding="utf-8")
            self.assertNotIn(FAKE_GITHUB, text)
            self.assertIn("[REDACTED]", text)


# ---------------------------------------------------------------- packaging

class PackagingTests(unittest.TestCase):
    def test_readme_has_no_em_dash(self):
        text = Path(os.path.join(TREE, "README.md")).read_text(
            encoding="utf-8")
        self.assertNotIn(EM_DASH, text)

    def test_build_zip_modes_and_contents(self):
        build_zip = os.path.join(TREE, "build_zip.py")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tree-repo-sync-check.zip")
            proc = subprocess.run(
                [sys.executable, build_zip, "--out", out],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.isfile(out))
            with zipfile.ZipFile(out) as zf:
                infos = zf.infolist()
            names = [info.filename for info in infos]
            self.assertNotIn("BUILD_REPORT.md", names)
            self.assertFalse([n for n in names
                              if n.endswith(".zip")])
            self.assertFalse([n for n in names
                              if n.startswith("logs/")])
            self.assertFalse([n for n in names
                              if "__pycache__" in n])
            scripts = {"tree_repo_sync_check.py", "run_tests.sh",
                       "build_zip.py"}
            for info in infos:
                mode = info.external_attr >> 16
                self.assertEqual(info.create_system, 3,
                                 info.filename)
                if info.is_dir():
                    self.assertEqual(mode, 0o40755, info.filename)
                elif info.filename in scripts:
                    self.assertEqual(mode, 0o100755, info.filename)
                else:
                    self.assertEqual(mode, 0o100644, info.filename)

    def test_scripts_carry_the_exec_bit_on_disk(self):
        for name in ("tree_repo_sync_check.py", "run_tests.sh",
                     "build_zip.py"):
            path = os.path.join(TREE, name)
            self.assertTrue(os.access(path, os.X_OK), name)


if __name__ == "__main__":
    unittest.main()
