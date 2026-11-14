"""Refresh pass tests, against the local fake server."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.api import GitHubClient  # noqa: E402
from board.cache import BoardCache  # noqa: E402
from board.flags import RepoHealth, compute_flags  # noqa: E402
from board.refresh import refresh_org  # noqa: E402
from helpers import (iso_days_ago, make_default_fixtures,  # noqa: E402
                     make_error_fixtures, make_rate_limit_fixtures,
                     start_fake_github, stop_fake_github)


def _by_name(result):
    return {row.name: row for row in result.rows}


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tmp.name, "cache.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _refresh(self, fixtures, cache=None, **kwargs):
        server, base_url = start_fake_github(fixtures)
        try:
            client = GitHubClient(base_url=base_url)
            cache = cache or BoardCache(self.cache_path)
            result = refresh_org(client, "TEST-ORG", cache, **kwargs)
            return result, cache, server
        finally:
            stop_fake_github(server)

    def test_full_refresh_fetches_every_repo(self):
        result, cache, _server = self._refresh(
            make_default_fixtures())
        self.assertEqual(len(result.rows), 7)
        self.assertEqual(result.fresh_count, 7)
        self.assertEqual(result.cached_count, 0)
        self.assertEqual(result.unchecked_count, 0)
        self.assertFalse(result.rate_limited)
        self.assertEqual(result.errors, [])
        self.assertEqual([row.name for row in result.rows],
                         ["aurora", "bare-bones", "empty-shell",
                          "no-license-lib", "placeholder-only",
                          "pushed-lies", "stale-widget"])
        self.assertEqual(cache.org, "TEST-ORG")
        self.assertIsNotNone(cache.fetched_at)

    def test_board_shows_the_real_commit_date_not_pushed_at(self):
        result, _cache, _server = self._refresh(
            make_default_fixtures())
        pushed_lies = _by_name(result)["pushed-lies"]
        # The listing claims yesterday; the real commit is old.
        self.assertEqual(pushed_lies.pushed_at, iso_days_ago(1))
        self.assertEqual(pushed_lies.last_commit_date,
                         iso_days_ago(200))
        self.assertNotEqual(pushed_lies.last_commit_date,
                            pushed_lies.pushed_at)
        kinds = [flag.kind
                 for flag in compute_flags(pushed_lies)]
        self.assertIn("stale", kinds)

    def test_row_fields_come_from_the_right_endpoints(self):
        result, _cache, _server = self._refresh(
            make_default_fixtures())
        rows = _by_name(result)
        aurora = rows["aurora"]
        self.assertEqual(aurora.last_commit_sha, "a" * 40)
        self.assertEqual(aurora.file_count, 7)
        self.assertIn(".github/workflows/ci.yml", aurora.tree_paths)
        self.assertEqual(aurora.latest_release_tag, "v1.2.0")
        self.assertFalse(aurora.from_cache)
        empty = rows["empty-shell"]
        self.assertIsNone(empty.last_commit_date)
        self.assertIsNone(empty.last_commit_sha)
        self.assertEqual(empty.file_count, 0)
        self.assertEqual(empty.tree_paths, [])
        self.assertIsNone(empty.latest_release_tag)
        bare = rows["bare-bones"]
        self.assertIsNone(bare.latest_release_tag)

    def test_refresh_stores_etags_from_the_server(self):
        _result, cache, _server = self._refresh(
            make_default_fixtures())
        etag = cache.get_etag(
            "/repos/TEST-ORG/aurora/commits?per_page=1")
        self.assertIsNotNone(etag)
        self.assertTrue(etag.startswith('"fake-'))

    def test_cached_repo_is_reused_without_detail_calls(self):
        fixtures = make_default_fixtures()
        listing = [repo for repo in fixtures["repos"]
                   if repo["name"] == "aurora"][0]
        cache = BoardCache(self.cache_path)
        cached = RepoHealth(
            name="aurora",
            html_url="https://github.com/TEST-ORG/aurora",
            description="A healthy example repo.",
            topics=["example"],
            pushed_at=listing["pushed_at"],
            last_commit_date=iso_days_ago(2),
            last_commit_sha="a" * 40,
            file_count=7,
            tree_paths=["README.md"],
            latest_release_tag="v1.2.0",
            fetched_at="2026-11-13T12:00:00+00:00",
        )
        cache.set_repo("aurora", cached.to_dict())
        cache.save()
        server, base_url = start_fake_github(fixtures)
        try:
            client = GitHubClient(base_url=base_url)
            result = refresh_org(client, "TEST-ORG", cache)
            counts = server.fake_state
        finally:
            stop_fake_github(server)
        self.assertEqual(result.cached_count, 1)
        self.assertEqual(result.fresh_count, 6)
        aurora = _by_name(result)["aurora"]
        self.assertTrue(aurora.from_cache)
        self.assertEqual(aurora.fetched_at,
                         "2026-11-13T12:00:00+00:00")
        self.assertEqual(
            counts.count_for("/repos/TEST-ORG/aurora/commits"), 0)
        self.assertEqual(
            counts.count_for("/repos/TEST-ORG/aurora/git/trees"), 0)
        self.assertEqual(
            counts.count_for("/repos/TEST-ORG/aurora/releases"), 0)

    def test_stale_cache_is_refetched(self):
        fixtures = make_default_fixtures()
        cache = BoardCache(self.cache_path)
        cached = RepoHealth(name="aurora", pushed_at="2001-01-01T00:00:00Z")
        cache.set_repo("aurora", cached.to_dict())
        cache.save()
        result, _cache, _server = self._refresh(fixtures, cache=cache)
        self.assertEqual(result.cached_count, 0)
        self.assertEqual(result.fresh_count, 7)
        self.assertFalse(_by_name(result)["aurora"].from_cache)

    def test_rate_limit_stops_cleanly_and_keeps_rows(self):
        fixtures = make_rate_limit_fixtures()
        listing = [repo for repo in fixtures["repos"]
                   if repo["name"] == "aurora"][0]
        cache = BoardCache(self.cache_path)
        cached = RepoHealth(
            name="aurora",
            html_url="https://github.com/TEST-ORG/aurora",
            description="A healthy example repo.",
            topics=["example"],
            pushed_at=listing["pushed_at"],
            last_commit_date=iso_days_ago(2),
            last_commit_sha="a" * 40,
            file_count=7,
            tree_paths=["README.md"],
            latest_release_tag="v1.2.0",
            fetched_at="2026-11-13T12:00:00+00:00",
        )
        cache.set_repo("aurora", cached.to_dict())
        cache.save()
        result, _cache, _server = self._refresh(fixtures, cache=cache)
        self.assertTrue(result.rate_limited)
        self.assertIsInstance(result.rate_reset_at, int)
        self.assertEqual(result.cached_count, 1)
        self.assertEqual(result.fresh_count, 0)
        self.assertEqual(result.unchecked_count, 6)
        self.assertEqual(len(result.rows), 7)
        rows = _by_name(result)
        self.assertTrue(rows["aurora"].from_cache)
        for name in ("bare-bones", "empty-shell", "no-license-lib",
                     "placeholder-only", "pushed-lies",
                     "stale-widget"):
            row = rows[name]
            self.assertIsNone(row.last_commit_date)
            self.assertIsNone(row.last_commit_sha)
            self.assertIsNone(row.file_count)
            self.assertEqual(row.tree_paths, [])
            self.assertIsNone(row.latest_release_tag)
        self.assertTrue(any("rate limit" in error.lower()
                            for error in result.errors))

    def test_rate_limit_at_listing_returns_empty_result(self):
        fixtures = make_default_fixtures()
        fixtures["rate_limit_listing"] = True
        result, _cache, _server = self._refresh(fixtures)
        self.assertTrue(result.rate_limited)
        self.assertIsInstance(result.rate_reset_at, int)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.errors, [
            "GitHub rate limit hit while listing repos: "
            "API rate limit exceeded for 127.0.0.1."])

    def test_per_repo_error_is_recorded_and_others_continue(self):
        result, _cache, _server = self._refresh(
            make_error_fixtures())
        self.assertFalse(result.rate_limited)
        self.assertEqual(result.fresh_count, 6)
        self.assertEqual(result.unchecked_count, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("no-license-lib", result.errors[0])
        row = _by_name(result)["no-license-lib"]
        self.assertIsNone(row.file_count)

    def test_per_repo_error_keeps_the_cached_row(self):
        fixtures = make_error_fixtures()
        cache = BoardCache(self.cache_path)
        cached = RepoHealth(
            name="no-license-lib",
            pushed_at="2001-01-01T00:00:00Z",
            last_commit_date=iso_days_ago(5),
            last_commit_sha="c" * 40,
            file_count=3,
            tree_paths=["README.md"],
            fetched_at="2026-11-13T12:00:00+00:00",
        )
        cache.set_repo("no-license-lib", cached.to_dict())
        cache.save()
        result, _cache, _server = self._refresh(fixtures, cache=cache)
        self.assertEqual(result.cached_count, 1)
        self.assertEqual(result.unchecked_count, 0)
        row = _by_name(result)["no-license-lib"]
        self.assertTrue(row.from_cache)
        self.assertEqual(row.file_count, 3)

    def test_cancel_stops_cleanly_with_no_error(self):
        calls = {"count": 0}

        def cancel():
            calls["count"] += 1
            return calls["count"] >= 2

        result, _cache, _server = self._refresh(
            make_default_fixtures(), cancel=cancel)
        self.assertFalse(result.rate_limited)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.fresh_count, 1)
        self.assertEqual(result.unchecked_count, 6)
        self.assertEqual(len(result.rows), 7)
        self.assertEqual(result.rows[0].name, "aurora")
        self.assertIsNotNone(result.rows[0].last_commit_date)
        self.assertIsNone(result.rows[1].last_commit_date)

    def test_progress_callback_reports_each_step(self):
        calls = []

        def progress(kind, current, total, name):
            calls.append((kind, current, total, name))

        result, _cache, _server = self._refresh(
            make_default_fixtures(), progress_cb=progress)
        self.assertEqual(calls[0], ("listing", 0, 0, "TEST-ORG"))
        repo_calls = [call for call in calls if call[0] == "repo"]
        self.assertEqual(len(repo_calls), 7)
        self.assertEqual(repo_calls[0],
                         ("repo", 1, 7, "aurora"))
        self.assertEqual(repo_calls[-1],
                         ("repo", 7, 7, "stale-widget"))
        self.assertEqual(calls[-1], ("done", 7, 7, ""))
        self.assertEqual(len(result.rows), 7)


if __name__ == "__main__":
    unittest.main()
