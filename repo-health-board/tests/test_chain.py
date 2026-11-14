"""End-to-end chain tests: fetch then flag against the local fake
server, run as subprocesses. No test touches the live GitHub API:
BOARD_BASE_URL points fetch at the fake server, and XDG_DATA_HOME
points the data dir at a temp dir."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.api import GitHubClient  # noqa: E402
from board.cache import BoardCache  # noqa: E402
from board.export import format_board_text  # noqa: E402
from board.flags import RepoHealth, compute_flags, suite_status  # noqa: E402
from board.refresh import refresh_org  # noqa: E402
from helpers import (make_default_fixtures,  # noqa: E402
                     make_rate_limit_fixtures, start_fake_github,
                     stop_fake_github)

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.env = dict(os.environ)
        self.env["XDG_DATA_HOME"] = self.data_dir
        self.env.pop("BOARD_BASE_URL", None)
        self.env.pop("REPO_HEALTH_BOARD_API_URL", None)
        self.server = None
        self.base_url = None

    def tearDown(self):
        if self.server is not None:
            stop_fake_github(self.server)
        self.tmp.cleanup()

    def _start_fake(self, fixtures):
        self.server, self.base_url = start_fake_github(fixtures)
        self.env["BOARD_BASE_URL"] = self.base_url

    def _run(self, *args):
        return subprocess.run(list(args), cwd=TREE, env=self.env,
                              capture_output=True, text=True,
                              timeout=120)

    @property
    def board_dir(self):
        return os.path.join(self.data_dir, "repo-health-board")

    def _load_json(self, name):
        with open(os.path.join(self.board_dir, name),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_fetch_then_flag_matches_refresh_and_compute(self):
        self._start_fake(make_default_fixtures())
        fetch = self._run(sys.executable, "-m", "board.fetch",
                          "--org", "TEST-ORG")
        self.assertEqual(fetch.returncode, 0, fetch.stderr)
        flag = self._run(sys.executable, "-m", "board.flag")
        self.assertEqual(flag.returncode, 0, flag.stderr)
        flagged = self._load_json("flagged.json")
        self.assertEqual(flagged["org"], "TEST-ORG")
        self.assertFalse(flagged["rate_limited"])
        self.assertEqual(flagged["counts"],
                         {"total": 7, "flagged": 6,
                          "unchecked": 0})
        # Independently recompute from the same fake server.
        cache = BoardCache(os.path.join(self.tmp.name,
                                        "check-cache.json"))
        client = GitHubClient(base_url=self.base_url)
        result = refresh_org(client, "TEST-ORG", cache)
        expected = {}
        for row in result.rows:
            health = row.to_dict()
            del health["fetched_at"]
            expected[row.name] = (
                health,
                [flag_.kind for flag_ in compute_flags(row)],
                suite_status(row))
        for row in flagged["rows"]:
            health = dict(row["health"])
            del health["fetched_at"]
            kinds = [flag_["kind"] for flag_ in row["flags"]]
            want_health, want_kinds, want_suite = \
                expected[row["health"]["name"]]
            self.assertEqual(health, want_health)
            self.assertEqual(kinds, want_kinds)
            self.assertEqual(row["suite"], want_suite)
        # The chain's text board matches format_board_text on the
        # same data.
        rows_with_flags = []
        for row in flagged["rows"]:
            health = RepoHealth.from_dict(row["health"])
            rows_with_flags.append((health, compute_flags(health)))
        want_text = format_board_text(rows_with_flags,
                                      flagged["org"],
                                      flagged["fetched_at"])
        with open(os.path.join(self.board_dir, "board.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), want_text)

    def test_rate_limited_chain_still_flags_partial_data(self):
        self._start_fake(make_rate_limit_fixtures())
        fetch = self._run(sys.executable, "-m", "board.fetch",
                          "--org", "TEST-ORG")
        self.assertEqual(fetch.returncode, 1)
        flag = self._run(sys.executable, "-m", "board.flag")
        self.assertEqual(flag.returncode, 0, flag.stderr)
        flagged = self._load_json("flagged.json")
        self.assertTrue(flagged["rate_limited"])
        self.assertEqual(flagged["counts"],
                         {"total": 7, "flagged": 1,
                          "unchecked": 6})
        rows = {row["health"]["name"]: row
                for row in flagged["rows"]}
        self.assertEqual(rows["bare-bones"]["suite"], "unknown")
        self.assertEqual(rows["aurora"]["suite"], "has CI")

    def test_wrapper_scripts_run_the_chain(self):
        # Run the wrappers through bash: a clone stores every file
        # 100644, so executing them directly would fail there even
        # though the Release zip carries the exec bits.
        self._start_fake(make_default_fixtures())
        fetch_help = self._run("bash", os.path.join(TREE, "board-fetch"),
                               "--help")
        self.assertEqual(fetch_help.returncode, 0)
        self.assertIn("board-fetch", fetch_help.stdout)
        flag_help = self._run("bash", os.path.join(TREE, "board-flag"),
                              "--help")
        self.assertEqual(flag_help.returncode, 0)
        self.assertIn("board-flag", flag_help.stdout)
        fetch = self._run("bash", os.path.join(TREE, "board-fetch"),
                          "--org", "TEST-ORG")
        self.assertEqual(fetch.returncode, 0, fetch.stderr)
        flag = self._run("bash", os.path.join(TREE, "board-flag"))
        self.assertEqual(flag.returncode, 0, flag.stderr)
        self.assertTrue(os.path.isfile(
            os.path.join(self.board_dir, "repos.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.board_dir, "flagged.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.board_dir, "board.txt")))


if __name__ == "__main__":
    unittest.main()
