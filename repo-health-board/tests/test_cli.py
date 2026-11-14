"""CLI tests, run as subprocesses against the local fake server.

The CLI never touches the live GitHub API in tests: the
REPO_HEALTH_BOARD_API_URL hook points it at the fake server, and
XDG_DATA_HOME points its settings, cache, and logs at a temp dir.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (make_default_fixtures, start_fake_github,  # noqa: E402
                     stop_fake_github)

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.env = dict(os.environ)
        self.env["XDG_DATA_HOME"] = self.data_dir
        self.env.pop("REPO_HEALTH_BOARD_API_URL", None)
        self.server = None

    def tearDown(self):
        if self.server is not None:
            stop_fake_github(self.server)
        self.tmp.cleanup()

    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "board"] + list(args),
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=120)

    def _start_fake(self):
        self.server, base_url = start_fake_github(
            make_default_fixtures())
        self.env["REPO_HEALTH_BOARD_API_URL"] = base_url
        return base_url

    def test_help_exits_zero(self):
        result = self._run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("board-cli", result.stdout)
        self.assertIn("refresh", result.stdout)
        self.assertIn("show", result.stdout)
        self.assertIn("export", result.stdout)
        self.assertIn("debug-report", result.stdout)

    def test_no_subcommand_prints_help_and_exits_zero(self):
        result = self._run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("board-cli", result.stdout)

    def test_version(self):
        result = self._run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Repo Health Board 0.1.0", result.stdout)

    def test_show_with_empty_cache(self):
        result = self._run_cli("show")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No cached data yet", result.stdout)
        self.assertIn("board-cli refresh", result.stdout)

    def test_export_with_empty_cache_exits_nonzero(self):
        result = self._run_cli("export")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No cached data yet", result.stderr)

    def test_refresh_show_and_export_against_fake_server(self):
        self._start_fake()
        refresh = self._run_cli("refresh", "--org", "TEST-ORG")
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        self.assertIn("Repo Health Board: TEST-ORG", refresh.stdout)
        self.assertIn("aurora | ", refresh.stdout)
        self.assertIn("pushed-lies | ", refresh.stdout)
        self.assertIn("Checking 1 of 7: aurora", refresh.stdout)
        self.assertIn("Fetched 7 repos: 7 fresh, 0 cached, "
                      "0 unchecked", refresh.stdout)
        self.assertIn("7 repos, 6 flagged, 1 ok", refresh.stdout)
        # The chain wrote its files into the data dir.
        board_dir = os.path.join(self.data_dir,
                                 "repo-health-board")
        for name in ("repos.json", "flagged.json", "board.txt",
                     "cache.json"):
            self.assertTrue(os.path.isfile(
                os.path.join(board_dir, name)), name)
        # The cache now holds the board: show reads it back.
        show = self._run_cli("show")
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("Repo Health Board: TEST-ORG", show.stdout)
        self.assertIn("aurora | ", show.stdout)
        # Export to a file.
        out_path = os.path.join(self.tmp.name, "board.txt")
        export = self._run_cli("export", "--out", out_path)
        self.assertEqual(export.returncode, 0, export.stderr)
        self.assertIn("Board written to %s" % out_path,
                      export.stdout)
        with open(out_path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Repo Health Board: TEST-ORG", content)
        self.assertIn("aurora | ", content)
        self.assertIn("7 repos, 6 flagged, 1 ok", content)
        # Export to stdout.
        export_stdout = self._run_cli("export")
        self.assertEqual(export_stdout.returncode, 0)
        self.assertIn("Repo Health Board: TEST-ORG",
                      export_stdout.stdout)

    def test_second_refresh_reuses_the_cache(self):
        self._start_fake()
        first = self._run_cli("refresh", "--org", "TEST-ORG")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self._run_cli("refresh", "--org", "TEST-ORG")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Fetched 7 repos: 0 fresh, 7 cached, "
                      "0 unchecked", second.stdout)

    def test_debug_report_writes_a_file_and_prints_the_path(self):
        self._start_fake()
        result = self._run_cli("debug-report")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Debug report written to ", result.stdout)
        path = result.stdout.split(
            "Debug report written to ", 1)[1].splitlines()[0].strip()
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("repo-health-board 0.1.0", content)
        self.assertIn("== Context ==", content)


if __name__ == "__main__":
    unittest.main()
