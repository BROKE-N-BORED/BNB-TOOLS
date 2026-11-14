"""GitHub API client tests, against the local fake server."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from board.api import (ApiError, GitHubClient, RateLimitError,  # noqa: E402
                       fetch_latest_commit, fetch_latest_release,
                       fetch_org_repos, fetch_tree)
from helpers import (make_default_fixtures,  # noqa: E402
                     make_many_repos_fixtures,
                     make_rate_limit_fixtures, start_fake_github,
                     stop_fake_github)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server, self.base_url = start_fake_github(
            make_default_fixtures())
        self.client = GitHubClient(base_url=self.base_url)

    def tearDown(self):
        stop_fake_github(self.server)

    def test_get_json_returns_status_payload_and_headers(self):
        status, payload, headers = self.client.get_json(
            "/orgs/TEST-ORG/repos?per_page=100")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 7)
        self.assertEqual(payload[0]["name"], "aurora")
        self.assertIn("etag", headers)

    def test_get_json_sends_accept_and_user_agent(self):
        self.client.get_json("/orgs/TEST-ORG/repos?per_page=100")
        _method, _path, headers = \
            self.server.fake_state.recorded_requests[-1]
        self.assertEqual(headers.get("accept"),
                         "application/vnd.github+json")
        self.assertTrue(headers.get("user-agent", "").startswith(
            "Repo Health Board/"))

    def test_get_json_304_returns_none_body(self):
        _status, _payload, headers = self.client.get_json(
            "/orgs/TEST-ORG/repos?per_page=100")
        etag = headers.get("etag")
        self.assertIsNotNone(etag)
        status, payload, _headers = self.client.get_json(
            "/orgs/TEST-ORG/repos?per_page=100", etag=etag)
        self.assertEqual(status, 304)
        self.assertIsNone(payload)

    def test_get_json_404_raises_api_error(self):
        with self.assertRaises(ApiError) as caught:
            self.client.get_json("/orgs/TEST-ORG/repos/nope")
        self.assertEqual(caught.exception.status, 404)
        self.assertIn("Not Found", caught.exception.message)

    def test_rate_limit_403_raises_rate_limit_error(self):
        server, base_url = start_fake_github(
            make_rate_limit_fixtures())
        try:
            client = GitHubClient(base_url=base_url)
            with self.assertRaises(RateLimitError) as caught:
                client.get_json(
                    "/repos/TEST-ORG/bare-bones/commits?per_page=1")
            self.assertEqual(caught.exception.status, 403)
            self.assertIsInstance(caught.exception.reset_at, int)
            self.assertIn("rate limit",
                          caught.exception.message.lower())
        finally:
            stop_fake_github(server)

    def test_non_rate_limit_403_is_a_plain_api_error(self):
        fixtures = make_default_fixtures()
        for repo in fixtures["repos"]:
            if repo["name"] == "aurora":
                repo["forbidden"] = True
        server, base_url = start_fake_github(fixtures)
        try:
            client = GitHubClient(base_url=base_url)
            with self.assertRaises(ApiError) as caught:
                client.get_json(
                    "/repos/TEST-ORG/aurora/commits?per_page=1")
            self.assertIs(type(caught.exception), ApiError)
            self.assertEqual(caught.exception.status, 403)
            self.assertIsNone(caught.exception.reset_at)
        finally:
            stop_fake_github(server)


class NoTokenTests(unittest.TestCase):
    def test_no_authorization_header_on_any_request(self):
        server, base_url = start_fake_github(make_default_fixtures())
        try:
            client = GitHubClient(base_url=base_url)
            repos = fetch_org_repos(client, "TEST-ORG")
            for repo in repos:
                fetch_latest_commit(client, "TEST-ORG", repo["name"])
                fetch_tree(client, "TEST-ORG", repo["name"],
                           "a" * 40)
                fetch_latest_release(client, "TEST-ORG", repo["name"])
            recorded = server.fake_state.recorded_requests
            self.assertGreater(len(recorded), 20)
            for _method, path, headers in recorded:
                self.assertNotIn("authorization", headers,
                                 "Authorization sent on %s" % path)
        finally:
            stop_fake_github(server)


class FetchHelpersTests(unittest.TestCase):
    def setUp(self):
        self.server, self.base_url = start_fake_github(
            make_default_fixtures())
        self.client = GitHubClient(base_url=self.base_url)

    def tearDown(self):
        stop_fake_github(self.server)

    def test_fetch_org_repos_lists_every_repo(self):
        repos = fetch_org_repos(self.client, "TEST-ORG")
        names = [repo["name"] for repo in repos]
        self.assertEqual(names, ["aurora", "bare-bones",
                                 "empty-shell", "no-license-lib",
                                 "placeholder-only", "pushed-lies",
                                 "stale-widget"])

    def test_fetch_org_repos_follows_pagination(self):
        server, base_url = start_fake_github(
            make_many_repos_fixtures(105))
        try:
            client = GitHubClient(base_url=base_url)
            repos = fetch_org_repos(client, "TEST-ORG")
            self.assertEqual(len(repos), 105)
            self.assertEqual(repos[0]["name"], "repo-000")
            self.assertEqual(repos[-1]["name"], "repo-104")
        finally:
            stop_fake_github(server)

    def test_fetch_latest_commit_returns_sha_and_date(self):
        commit = fetch_latest_commit(self.client, "TEST-ORG", "aurora")
        self.assertEqual(commit["sha"], "a" * 40)
        self.assertTrue(commit["date"].endswith("Z"))

    def test_fetch_latest_commit_empty_repo_returns_none(self):
        commit = fetch_latest_commit(self.client, "TEST-ORG",
                                     "empty-shell")
        self.assertIsNone(commit)

    def test_fetch_tree_returns_paths(self):
        tree = fetch_tree(self.client, "TEST-ORG", "aurora", "a" * 40)
        paths = [entry["path"] for entry in tree["tree"]]
        self.assertIn("README.md", paths)
        self.assertIn(".github/workflows/ci.yml", paths)

    def test_fetch_tree_without_sha_returns_empty_tree(self):
        tree = fetch_tree(self.client, "TEST-ORG", "empty-shell", None)
        self.assertEqual(tree["tree"], [])
        self.assertFalse(tree["truncated"])
        self.assertEqual(
            self.server.fake_state.count_for("/git/trees/"), 0)

    def test_fetch_latest_release_returns_tag(self):
        release = fetch_latest_release(self.client, "TEST-ORG",
                                       "aurora")
        self.assertEqual(release, {"tag": "v1.2.0"})

    def test_fetch_latest_release_without_releases_returns_none(self):
        release = fetch_latest_release(self.client, "TEST-ORG",
                                       "bare-bones")
        self.assertIsNone(release)


if __name__ == "__main__":
    unittest.main()
