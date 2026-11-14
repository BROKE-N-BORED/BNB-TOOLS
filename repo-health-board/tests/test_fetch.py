"""Standalone fetch tests, run as subprocesses against the local
fake server. No test touches the live GitHub API: BOARD_BASE_URL
points fetch at the fake server, and XDG_DATA_HOME points its
data dir at a temp dir."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (iso_days_ago, make_default_fixtures,  # noqa: E402
                     make_error_fixtures,
                     make_rate_limit_fixtures, start_fake_github,
                     stop_fake_github)

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.env = dict(os.environ)
        self.env["XDG_DATA_HOME"] = self.data_dir
        self.env.pop("BOARD_BASE_URL", None)
        self.env.pop("REPO_HEALTH_BOARD_API_URL", None)
        self.server = None

    def tearDown(self):
        if self.server is not None:
            stop_fake_github(self.server)
        self.tmp.cleanup()

    def _run_fetch(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "board.fetch"] + list(args),
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=120)

    def _start_fake(self, fixtures=None):
        self.server, base_url = start_fake_github(
            fixtures if fixtures is not None
            else make_default_fixtures())
        self.env["BOARD_BASE_URL"] = base_url
        return base_url

    @property
    def repos_path(self):
        return os.path.join(self.data_dir, "repo-health-board",
                            "repos.json")

    @property
    def cache_path(self):
        return os.path.join(self.data_dir, "repo-health-board",
                            "cache.json")

    def _load_repos_json(self):
        with open(self.repos_path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_help_exits_zero(self):
        result = self._run_fetch("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("board-fetch", result.stdout)
        self.assertIn("--org", result.stdout)
        self.assertIn("--out", result.stdout)
        self.assertIn("--base-url", result.stdout)

    def test_fetch_writes_repos_json_with_real_commit_dates(self):
        self._start_fake()
        result = self._run_fetch("--org", "TEST-ORG")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checking 1 of 7: aurora", result.stdout)
        self.assertIn("Checking 7 of 7: stale-widget",
                      result.stdout)
        self.assertIn("Fetched 7 repos: 7 fresh, 0 cached, "
                      "0 unchecked", result.stdout)
        self.assertTrue(os.path.isfile(self.repos_path))
        self.assertTrue(os.path.isfile(self.cache_path))
        data = self._load_repos_json()
        self.assertEqual(data["org"], "TEST-ORG")
        self.assertTrue(data["fetched_at"])
        self.assertFalse(data["rate_limited"])
        self.assertIsNone(data["rate_reset_at"])
        self.assertEqual(len(data["repos"]), 7)
        by_name = {repo["name"]: repo for repo in data["repos"]}
        # The listing claims yesterday; the real commit is old.
        pushed_lies = by_name["pushed-lies"]
        self.assertEqual(pushed_lies["pushed_at"],
                         iso_days_ago(1))
        self.assertEqual(pushed_lies["last_commit_date"],
                         iso_days_ago(200))
        self.assertNotEqual(pushed_lies["last_commit_date"],
                            pushed_lies["pushed_at"])
        aurora = by_name["aurora"]
        self.assertEqual(aurora["last_commit_sha"], "a" * 40)
        self.assertEqual(aurora["file_count"], 7)
        self.assertEqual(aurora["latest_release_tag"], "v1.2.0")

    def test_base_url_flag_overrides_env(self):
        base_url = self._start_fake()
        self.env.pop("BOARD_BASE_URL")
        result = self._run_fetch("--org", "TEST-ORG",
                                 "--base-url", base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(self.repos_path))

    def test_rate_limit_exits_one_with_partial_file(self):
        self._start_fake(make_rate_limit_fixtures())
        result = self._run_fetch("--org", "TEST-ORG")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(os.path.isfile(self.repos_path))
        data = self._load_repos_json()
        self.assertTrue(data["rate_limited"])
        self.assertIsInstance(data["rate_reset_at"], int)
        self.assertEqual(len(data["repos"]), 7)
        by_name = {repo["name"]: repo for repo in data["repos"]}
        self.assertIsNotNone(by_name["aurora"]["last_commit_date"])
        self.assertIsNone(by_name["bare-bones"]["file_count"])
        self.assertIsNone(
            by_name["bare-bones"]["last_commit_date"])
        lines = result.stdout.splitlines()
        self.assertTrue(any(line.startswith("Rate limit reached: ")
                            for line in lines), result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_rate_limit_at_listing_exits_one_with_empty_file(self):
        fixtures = make_default_fixtures()
        fixtures["rate_limit_listing"] = True
        self._start_fake(fixtures)
        result = self._run_fetch("--org", "TEST-ORG")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(os.path.isfile(self.repos_path))
        data = self._load_repos_json()
        self.assertTrue(data["rate_limited"])
        self.assertEqual(data["repos"], [])

    def test_per_repo_error_exits_one_with_partial_file(self):
        self._start_fake(make_error_fixtures())
        result = self._run_fetch("--org", "TEST-ORG")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(os.path.isfile(self.repos_path))
        data = self._load_repos_json()
        self.assertFalse(data["rate_limited"])
        by_name = {repo["name"]: repo for repo in data["repos"]}
        self.assertIsNone(by_name["no-license-lib"]["file_count"])
        self.assertIsNotNone(by_name["aurora"]["last_commit_date"])
        self.assertIn("Error: no-license-lib", result.stdout)

    def test_unknown_org_exits_two(self):
        fixtures = make_default_fixtures()
        fixtures["unknown_org"] = True
        self._start_fake(fixtures)
        result = self._run_fetch("--org", "NOPE-ORG")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Not Found", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.isfile(self.repos_path))

    def test_empty_org_exits_two(self):
        self._start_fake({"org": "TEST-ORG", "repos": []})
        result = self._run_fetch("--org", "TEST-ORG")
        self.assertEqual(result.returncode, 2)
        self.assertIn("No repos found in org TEST-ORG.",
                      result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_network_down_exits_two(self):
        result = self._run_fetch("--org", "TEST-ORG",
                                 "--base-url", "http://127.0.0.1:1",
                                 "--timeout", "2")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not reach GitHub", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
