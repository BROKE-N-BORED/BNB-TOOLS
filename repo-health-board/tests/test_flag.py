"""Standalone flag tests, run as subprocesses. Flag reads a repos
JSON file (fetch output, or one made by hand) and writes flagged
JSON plus the text board. No network at all."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import iso_days_ago  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FULL_FILES = ["README.md", "LICENSE", ".gitignore", "SECURITY.md",
              "src/main.py", ".github/workflows/ci.yml"]


def make_handmade_repos_json():
    """A repos JSON made by hand, not by fetch: one healthy repo,
    one stale placeholder, one unchecked row."""
    return {
        "org": "HANDMADE-ORG",
        "fetched_at": "2026-11-14T12:00:00+00:00",
        "rate_limited": False,
        "rate_reset_at": None,
        "repos": [
            {
                "name": "healthy",
                "html_url": "https://github.com/x/healthy",
                "description": "A healthy example repo.",
                "topics": ["example"],
                "pushed_at": iso_days_ago(1),
                "last_commit_date": iso_days_ago(2),
                "last_commit_sha": "a" * 40,
                "file_count": 6,
                "tree_paths": list(FULL_FILES),
                "latest_release_tag": "v1.0.0",
                "fetched_at": "2026-11-14T12:00:00+00:00",
            },
            {
                "name": "stale-placeholder",
                "html_url": "https://github.com/x/stale",
                "description": "Nothing here yet but a README.",
                "topics": ["placeholder"],
                "pushed_at": iso_days_ago(1),
                "last_commit_date": iso_days_ago(200),
                "last_commit_sha": "b" * 40,
                "file_count": 1,
                "tree_paths": ["README.md"],
                "latest_release_tag": None,
                "fetched_at": "2026-11-14T12:00:00+00:00",
            },
            {
                "name": "unchecked-one",
                "html_url": "https://github.com/x/unchecked",
                "description": None,
                "topics": [],
                "pushed_at": iso_days_ago(1),
                "last_commit_date": None,
                "last_commit_sha": None,
                "file_count": None,
                "tree_paths": [],
                "latest_release_tag": None,
                "fetched_at": "2026-11-14T12:00:00+00:00",
            },
        ],
    }


class FlagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.env = dict(os.environ)
        self.env["XDG_DATA_HOME"] = self.data_dir
        self.in_path = os.path.join(self.tmp.name, "repos.json")
        self.out_path = os.path.join(self.tmp.name, "flagged.json")
        self.text_path = os.path.join(self.tmp.name, "board.txt")
        with open(self.in_path, "w", encoding="utf-8") as fh:
            json.dump(make_handmade_repos_json(), fh)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_flag(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "board.flag"] + list(args),
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=120)

    def _load_flagged(self, path=None):
        with open(path or self.out_path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_help_exits_zero(self):
        result = self._run_flag("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("board-flag", result.stdout)
        self.assertIn("--in", result.stdout)
        self.assertIn("--out", result.stdout)
        self.assertIn("--text", result.stdout)

    def test_flag_writes_flagged_json_and_text_board(self):
        result = self._run_flag("--in", self.in_path,
                                "--out", self.out_path,
                                "--text", self.text_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 repos, 2 flagged, 1 unchecked",
                      result.stdout)
        data = self._load_flagged()
        self.assertEqual(data["org"], "HANDMADE-ORG")
        self.assertEqual(data["fetched_at"],
                         "2026-11-14T12:00:00+00:00")
        self.assertFalse(data["rate_limited"])
        self.assertIsNone(data["rate_reset_at"])
        self.assertEqual(data["counts"],
                         {"total": 3, "flagged": 2,
                          "unchecked": 1})
        rows = {row["health"]["name"]: row for row in data["rows"]}
        healthy = rows["healthy"]
        self.assertEqual(healthy["flags"], [])
        self.assertEqual(healthy["suite"], "has CI")
        stale = rows["stale-placeholder"]
        kinds = [flag["kind"] for flag in stale["flags"]]
        self.assertEqual(kinds, ["placeholder", "missing-license",
                                 "missing-gitignore",
                                 "missing-security", "stale"])
        self.assertEqual(stale["suite"], "no CI file")
        unchecked = rows["unchecked-one"]
        kinds = [flag["kind"] for flag in unchecked["flags"]]
        self.assertEqual(kinds, ["missing-description",
                                 "missing-topics"])
        self.assertEqual(unchecked["suite"], "unknown")
        with open(self.text_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Repo Health Board: HANDMADE-ORG "
                      "(fetched 2026-11-14T12:00:00+00:00)", text)
        self.assertIn("healthy | ", text)
        self.assertIn("stale-placeholder | ", text)
        self.assertIn("unchecked-one | unknown | unknown | none | "
                      "no description, no topics", text)
        self.assertIn("3 repos, 2 flagged, 1 ok", text)

    def test_flag_carries_rate_limit_fields_through(self):
        payload = make_handmade_repos_json()
        payload["rate_limited"] = True
        payload["rate_reset_at"] = 1234567890
        with open(self.in_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        result = self._run_flag("--in", self.in_path,
                                "--out", self.out_path,
                                "--text", self.text_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self._load_flagged()
        self.assertTrue(data["rate_limited"])
        self.assertEqual(data["rate_reset_at"], 1234567890)

    def test_missing_input_exits_two(self):
        missing = os.path.join(self.tmp.name, "nope.json")
        result = self._run_flag("--in", missing,
                                "--out", self.out_path,
                                "--text", self.text_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("No such file", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.isfile(self.out_path))

    def test_bad_json_exits_two(self):
        with open(self.in_path, "w", encoding="utf-8") as fh:
            fh.write("not json{")
        result = self._run_flag("--in", self.in_path,
                                "--out", self.out_path,
                                "--text", self.text_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not valid JSON", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_wrong_shape_exits_two(self):
        with open(self.in_path, "w", encoding="utf-8") as fh:
            json.dump({"org": "HANDMADE-ORG"}, fh)
        result = self._run_flag("--in", self.in_path,
                                "--out", self.out_path,
                                "--text", self.text_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not look like fetch output",
                      result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_defaults_use_the_data_dir(self):
        default_dir = os.path.join(self.data_dir,
                                   "repo-health-board")
        os.makedirs(default_dir, exist_ok=True)
        with open(os.path.join(default_dir, "repos.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(make_handmade_repos_json(), fh)
        result = self._run_flag()
        self.assertEqual(result.returncode, 0, result.stderr)
        flagged = os.path.join(default_dir, "flagged.json")
        board = os.path.join(default_dir, "board.txt")
        self.assertTrue(os.path.isfile(flagged))
        self.assertTrue(os.path.isfile(board))
        data = self._load_flagged(flagged)
        self.assertEqual(data["counts"]["total"], 3)


if __name__ == "__main__":
    unittest.main()
