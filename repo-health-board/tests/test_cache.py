"""Cache tests: round-trip, ETags, corrupt file tolerance."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.cache import BoardCache  # noqa: E402
from board.flags import RepoHealth  # noqa: E402

DETAIL = RepoHealth(
    name="aurora",
    html_url="https://github.com/TEST-ORG/aurora",
    description="A healthy example repo.",
    topics=["example"],
    pushed_at="2026-11-13T12:00:00Z",
    last_commit_date="2026-11-12T12:00:00Z",
    last_commit_sha="a" * 40,
    file_count=7,
    tree_paths=["README.md", "LICENSE"],
    latest_release_tag="v1.2.0",
    fetched_at="2026-11-14T12:00:00+00:00",
).to_dict()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "board-cache.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_loads_empty(self):
        cache = BoardCache(self.path)
        self.assertIsNone(cache.org)
        self.assertIsNone(cache.fetched_at)
        self.assertIsNone(cache.get_repo("aurora"))
        self.assertIsNone(
            cache.get_etag("/repos/TEST-ORG/aurora/commits"))
        self.assertEqual(cache.repo_names(), [])

    def test_round_trip_preserves_rows_etags_and_org(self):
        cache = BoardCache(self.path)
        cache.org = "TEST-ORG"
        cache.fetched_at = "2026-11-14T12:00:00+00:00"
        cache.set_repo("aurora", DETAIL)
        cache.set_etag("/repos/TEST-ORG/aurora/commits?per_page=1",
                       '"fake-abc123"')
        cache.save()
        loaded = BoardCache(self.path)
        self.assertEqual(loaded.org, "TEST-ORG")
        self.assertEqual(loaded.fetched_at,
                         "2026-11-14T12:00:00+00:00")
        self.assertEqual(loaded.get_repo("aurora"), DETAIL)
        self.assertEqual(loaded.get_etag(
            "/repos/TEST-ORG/aurora/commits?per_page=1"),
            '"fake-abc123"')
        self.assertEqual(loaded.repo_names(), ["aurora"])
        health = RepoHealth.from_dict(loaded.get_repo("aurora"))
        self.assertEqual(health.last_commit_date,
                         "2026-11-12T12:00:00Z")
        self.assertEqual(health.file_count, 7)

    def test_corrupt_file_loads_empty_without_crashing(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("this is not json {{{")
        cache = BoardCache(self.path)
        self.assertIsNone(cache.org)
        self.assertEqual(cache.repo_names(), [])
        # And the cache still works after the bad load.
        cache.org = "TEST-ORG"
        cache.save()
        self.assertEqual(BoardCache(self.path).org, "TEST-ORG")

    def test_non_object_file_loads_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        cache = BoardCache(self.path)
        self.assertIsNone(cache.org)
        self.assertEqual(cache.repo_names(), [])

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        cache = BoardCache(self.path)
        cache.org = "TEST-ORG"
        cache.save()
        self.assertEqual(os.listdir(self.tmp.name),
                         ["board-cache.json"])
        cache.org = "OTHER-ORG"
        cache.save()
        self.assertEqual(os.listdir(self.tmp.name),
                         ["board-cache.json"])
        self.assertEqual(BoardCache(self.path).org, "OTHER-ORG")

    def test_save_creates_missing_parent_dirs(self):
        nested = os.path.join(self.tmp.name, "deep", "deeper",
                              "board-cache.json")
        cache = BoardCache(nested)
        cache.org = "TEST-ORG"
        cache.save()
        self.assertTrue(os.path.isfile(nested))


if __name__ == "__main__":
    unittest.main()
