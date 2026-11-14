"""Export format tests: exact line shape, no em-dashes."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.export import format_board_text, format_repo_line  # noqa: E402
from board.flags import Flag, RepoHealth, compute_flags  # noqa: E402


def _healthy():
    return RepoHealth(
        name="aurora",
        html_url="https://github.com/TEST-ORG/aurora",
        description="A healthy example repo.",
        topics=["example"],
        pushed_at="2026-11-13T12:00:00Z",
        last_commit_date="2026-11-12T12:00:00Z",
        last_commit_sha="a" * 40,
        file_count=7,
        tree_paths=["README.md", "LICENSE", ".gitignore",
                    "SECURITY.md", "src/main.py", "src/util.py",
                    ".github/workflows/ci.yml"],
        latest_release_tag="v1.2.0",
        fetched_at="2026-11-14T12:00:00+00:00",
    )


class ExportTests(unittest.TestCase):
    def test_healthy_repo_line(self):
        health = _healthy()
        line = format_repo_line(health, compute_flags(health))
        self.assertEqual(
            line, "aurora | 2026-11-12 | 7 files | v1.2.0 | ok")

    def test_flagged_repo_line(self):
        health = RepoHealth(
            name="placeholder-only",
            description="Nothing here yet but a README.",
            topics=["placeholder"],
            pushed_at="2026-11-13T12:00:00Z",
            last_commit_date="2026-11-10T12:00:00Z",
            last_commit_sha="d" * 40,
            file_count=1,
            tree_paths=["README.md"],
            latest_release_tag=None,
            fetched_at="2026-11-14T12:00:00+00:00",
        )
        line = format_repo_line(health, compute_flags(health))
        self.assertEqual(
            line, "placeholder-only | 2026-11-10 | 1 files | none | "
                  "placeholder, no LICENSE, no .gitignore, "
                  "no SECURITY.md")

    def test_unknown_repo_line(self):
        health = RepoHealth(
            name="mystery",
            description=None,
            topics=[],
            pushed_at="2026-11-13T12:00:00Z",
            fetched_at="2026-11-14T12:00:00+00:00",
        )
        line = format_repo_line(health, compute_flags(health))
        self.assertEqual(
            line, "mystery | unknown | unknown | none | "
                  "no description, no topics")

    def test_stale_flag_in_line(self):
        health = _healthy()
        health.name = "stale-widget"
        health.last_commit_date = "2026-05-01T12:00:00Z"
        flags = [Flag("stale", "stale (no commit in 90 days)")]
        line = format_repo_line(health, flags)
        self.assertEqual(
            line, "stale-widget | 2026-05-01 | 7 files | v1.2.0 | "
                  "stale (no commit in 90 days)")

    def test_board_text_header_lines_and_footer(self):
        healthy = _healthy()
        stale = _healthy()
        stale.name = "stale-widget"
        stale.last_commit_date = "2026-05-01T12:00:00Z"
        rows = [
            (healthy, compute_flags(healthy)),
            (stale, [Flag("stale", "stale (no commit in 90 days)")]),
        ]
        text = format_board_text(rows, "TEST-ORG",
                                 "2026-11-14T12:00:00+00:00")
        self.assertEqual(text,
                         "Repo Health Board: TEST-ORG "
                         "(fetched 2026-11-14T12:00:00+00:00)\n"
                         "aurora | 2026-11-12 | 7 files | v1.2.0 | ok\n"
                         "stale-widget | 2026-05-01 | 7 files | "
                         "v1.2.0 | stale (no commit in 90 days)\n"
                         "2 repos, 1 flagged, 1 ok\n")

    def test_board_text_with_no_rows(self):
        text = format_board_text([], "TEST-ORG",
                                 "2026-11-14T12:00:00+00:00")
        self.assertEqual(text,
                         "Repo Health Board: TEST-ORG "
                         "(fetched 2026-11-14T12:00:00+00:00)\n"
                         "0 repos, 0 flagged, 0 ok\n")

    def test_board_text_without_fetch_date(self):
        text = format_board_text([], "TEST-ORG", None)
        self.assertIn("(fetched unknown)", text)

    def test_no_em_dashes_in_any_output(self):
        healthy = _healthy()
        rows = [(healthy, compute_flags(healthy))]
        text = format_board_text(rows, "TEST-ORG",
                                 "2026-11-14T12:00:00+00:00")
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2014",
                         format_repo_line(healthy, []))


if __name__ == "__main__":
    unittest.main()
