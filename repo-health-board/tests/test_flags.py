"""Flag rule tests, proven against fixture-shaped RepoHealth rows."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.flags import (STALE_DAYS, RepoHealth, compute_flags,  # noqa: E402
                         suite_status)

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

FULL_TREE = ["README.md", "LICENSE", ".gitignore", "SECURITY.md",
             "src/main.py", "src/util.py",
             ".github/workflows/ci.yml"]


def _date(days_ago):
    when = NOW - timedelta(days=days_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _health(**overrides):
    values = {
        "name": "aurora",
        "html_url": "https://github.com/TEST-ORG/aurora",
        "description": "A healthy example repo.",
        "topics": ["example"],
        "pushed_at": _date(1),
        "last_commit_date": _date(2),
        "last_commit_sha": "a" * 40,
        "file_count": len(FULL_TREE),
        "tree_paths": list(FULL_TREE),
        "latest_release_tag": "v1.2.0",
        "fetched_at": "2026-11-14T12:00:00+00:00",
        "from_cache": False,
    }
    values.update(overrides)
    return RepoHealth(**values)


def _kinds(health, now=NOW):
    return [flag.kind for flag in compute_flags(health, now=now)]


class FlagRuleTests(unittest.TestCase):
    def test_stale_days_is_90(self):
        self.assertEqual(STALE_DAYS, 90)

    def test_healthy_repo_has_no_flags(self):
        self.assertEqual(_kinds(_health()), [])

    def test_placeholder_repo_with_only_a_readme(self):
        health = _health(tree_paths=["README.md"], file_count=1)
        kinds = _kinds(health)
        self.assertIn("placeholder", kinds)
        self.assertIn("missing-license", kinds)
        self.assertIn("missing-gitignore", kinds)
        self.assertIn("missing-security", kinds)
        self.assertNotIn("missing-readme", kinds)

    def test_empty_repo_is_a_placeholder_with_missing_files(self):
        health = _health(tree_paths=[], file_count=0,
                         last_commit_date=None, last_commit_sha=None,
                         latest_release_tag=None)
        kinds = _kinds(health)
        self.assertIn("placeholder", kinds)
        self.assertIn("missing-readme", kinds)
        self.assertIn("missing-license", kinds)
        self.assertIn("missing-gitignore", kinds)
        self.assertIn("missing-security", kinds)
        self.assertNotIn("stale", kinds)

    def test_unfetched_tree_earns_no_file_flags(self):
        health = _health(tree_paths=[], file_count=None)
        kinds = _kinds(health)
        self.assertNotIn("placeholder", kinds)
        self.assertNotIn("missing-readme", kinds)
        self.assertNotIn("missing-license", kinds)
        self.assertNotIn("missing-gitignore", kinds)
        self.assertNotIn("missing-security", kinds)

    def test_missing_readme(self):
        tree = ["LICENSE", ".gitignore", "SECURITY.md", "src/a.py"]
        self.assertEqual(_kinds(_health(tree_paths=tree,
                                        file_count=len(tree))),
                         ["missing-readme"])

    def test_missing_license(self):
        tree = ["README.md", ".gitignore", "SECURITY.md", "src/a.py"]
        self.assertEqual(_kinds(_health(tree_paths=tree,
                                        file_count=len(tree))),
                         ["missing-license"])

    def test_missing_gitignore(self):
        tree = ["README.md", "LICENSE", "SECURITY.md", "src/a.py"]
        self.assertEqual(_kinds(_health(tree_paths=tree,
                                        file_count=len(tree))),
                         ["missing-gitignore"])

    def test_missing_security(self):
        tree = ["README.md", "LICENSE", ".gitignore", "src/a.py"]
        self.assertEqual(_kinds(_health(tree_paths=tree,
                                        file_count=len(tree))),
                         ["missing-security"])

    def test_readme_under_docs_counts(self):
        tree = ["docs/README.md", "LICENSE", ".gitignore",
                "SECURITY.md", "src/a.py"]
        self.assertNotIn("missing-readme",
                         _kinds(_health(tree_paths=tree,
                                        file_count=len(tree))))

    def test_readme_match_is_case_insensitive(self):
        tree = ["ReadMe.MD", "license.txt", ".GITIGNORE",
                "security.MD", "src/a.py"]
        self.assertEqual(_kinds(_health(tree_paths=tree,
                                        file_count=len(tree))), [])

    def test_missing_description(self):
        for description in (None, "", "   "):
            self.assertIn("missing-description",
                          _kinds(_health(description=description)))

    def test_missing_topics(self):
        self.assertIn("missing-topics", _kinds(_health(topics=[])))

    def test_stale_repo(self):
        health = _health(last_commit_date=_date(91))
        self.assertIn("stale", _kinds(health))

    def test_fresh_repo_is_not_stale(self):
        health = _health(last_commit_date=_date(89))
        self.assertNotIn("stale", _kinds(health))

    def test_unknown_commit_date_is_not_stale(self):
        health = _health(last_commit_date=None)
        self.assertNotIn("stale", _kinds(health))

    def test_pushed_at_is_never_used_by_the_rules(self):
        # Listing says yesterday, real commit is old: stale.
        health = _health(pushed_at=_date(1),
                         last_commit_date=_date(200))
        self.assertIn("stale", _kinds(health))
        # Listing says old, real commit is fresh: not stale.
        health = _health(pushed_at=_date(200),
                         last_commit_date=_date(2))
        self.assertNotIn("stale", _kinds(health))

    def test_releases_are_not_a_flag(self):
        with_release = _kinds(_health(latest_release_tag="v1.0.0"))
        without = _kinds(_health(latest_release_tag=None))
        self.assertEqual(with_release, without)
        self.assertEqual(with_release, [])

    def test_flag_labels_are_plain_words(self):
        health = _health(tree_paths=["README.md"], file_count=1,
                         description=None, topics=[],
                         last_commit_date=_date(200))
        labels = [flag.label
                  for flag in compute_flags(health, now=NOW)]
        self.assertEqual(labels, ["placeholder", "no LICENSE",
                                  "no .gitignore", "no SECURITY.md",
                                  "no description", "no topics",
                                  "stale (no commit in 90 days)"])
        for label in labels:
            self.assertNotIn("\u2014", label)


class SuiteStatusTests(unittest.TestCase):
    def test_has_ci_with_yml_workflow(self):
        self.assertEqual(suite_status(_health()), "has CI")

    def test_has_ci_with_yaml_workflow(self):
        tree = ["README.md", ".github/workflows/build.yaml"]
        self.assertEqual(
            suite_status(_health(tree_paths=tree,
                                 file_count=len(tree))), "has CI")

    def test_no_ci_file_when_tree_fetched_without_workflows(self):
        tree = ["README.md", "LICENSE", ".gitignore", "SECURITY.md",
                "src/a.py"]
        self.assertEqual(
            suite_status(_health(tree_paths=tree,
                                 file_count=len(tree))), "no CI file")

    def test_unknown_when_tree_not_fetched(self):
        self.assertEqual(
            suite_status(_health(tree_paths=[], file_count=None)),
            "unknown")

    def test_suite_status_is_never_a_flag_kind(self):
        kinds = _kinds(_health(tree_paths=["README.md"],
                               file_count=1))
        self.assertNotIn("has CI", kinds)
        self.assertNotIn("no CI file", kinds)
        self.assertNotIn("unknown", kinds)


if __name__ == "__main__":
    unittest.main()
