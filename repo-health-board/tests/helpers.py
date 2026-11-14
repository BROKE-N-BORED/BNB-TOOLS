"""Shared test helpers: a fake GitHub API server and fixtures.

The fake server runs on 127.0.0.1 on an ephemeral port and serves
canned fixtures. No test touches the live GitHub API.

Public API (Worker 2's GUI tests import this too):
    start_fake_github(fixtures) -> (server, base_url)
    stop_fake_github(server)
    make_default_fixtures(org="TEST-ORG") -> fixtures dict

The server records every request on server.fake_state:
    recorded_requests: list of (method, path, headers dict with
        lowercase keys), for the no-Authorization-header test.
    request_counts: path -> number of times it was requested.

A repo fixture is a dict:
    name, description, topics, pushed_at (ISO),
    commits: list of commit payloads, or None for an empty repo,
    tree: list of paths (blobs), releases: list of {"tag_name":...}
    rate_limit: True makes every detail endpoint for the repo
        return a 403 rate-limit response.
    forbidden: True makes every detail endpoint return a plain
        403 (not a rate limit).
    error: an HTTP status (e.g. 500) every detail endpoint returns.
Fixtures may also carry "rate_limit_listing": True to make the
org repos list itself return a 403 rate-limit response, and
"unknown_org": True to make the org repos list return a 404
(the org does not exist).

Fake secrets, built from parts (concatenation), never written as
one literal: a full secret-shaped literal in a file trips secret
scanners on push, even with FAKE in it. The GitHub fixtures need
no tokens at all; these exist only for the scrub tests.
"""

import hashlib
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

FAKE_GITHUB = "ghp_" + "FAKE" * 9
FAKE_SK = "sk-" + "FAKE" * 6 + "1234"
FAKE_PASSWORD = "FAKEPASSWORD123"


def iso_days_ago(days, hour=12):
    """An ISO date N days ago, for stable stale/fresh fixtures."""
    when = datetime.now(timezone.utc) - timedelta(days=days)
    return when.replace(hour=hour, minute=0, second=0,
                        microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def commit_payload(sha, date):
    return {"sha": sha,
            "commit": {"committer": {"date": date},
                       "author": {"date": date},
                       "message": "test commit"}}


def make_default_fixtures(org="TEST-ORG"):
    """Seven repos covering every flag rule plus the critical
    pushed_at disagreement: pushed-lies lists a pushed_at of
    yesterday while its real latest commit is 200 days old."""
    fresh = iso_days_ago(2)
    pushed = iso_days_ago(1)
    old = iso_days_ago(200)
    full_files = ["README.md", "LICENSE", ".gitignore",
                  "SECURITY.md", "src/main.py", "src/util.py",
                  ".github/workflows/ci.yml"]
    repos = [
        {
            "name": "aurora",
            "description": "A healthy example repo.",
            "topics": ["example", "healthy"],
            "pushed_at": pushed,
            "commits": [commit_payload("a" * 40, fresh)],
            "tree": list(full_files),
            "releases": [{"tag_name": "v1.2.0"}],
        },
        {
            "name": "bare-bones",
            "description": None,
            "topics": [],
            "pushed_at": pushed,
            "commits": [commit_payload("b" * 40, iso_days_ago(3))],
            "tree": list(full_files),
            "releases": [],
        },
        {
            "name": "empty-shell",
            "description": "Created but never committed to.",
            "topics": ["empty"],
            "pushed_at": iso_days_ago(400),
            "commits": None,
            "tree": [],
            "releases": [],
        },
        {
            "name": "no-license-lib",
            "description": "A library with no license file.",
            "topics": ["library"],
            "pushed_at": pushed,
            "commits": [commit_payload("c" * 40, iso_days_ago(5))],
            "tree": ["README.md", "SECURITY.md", "src/main.py"],
            "releases": [{"tag_name": "v0.3.0"}],
        },
        {
            "name": "placeholder-only",
            "description": "Nothing here yet but a README.",
            "topics": ["placeholder"],
            "pushed_at": pushed,
            "commits": [commit_payload("d" * 40, iso_days_ago(4))],
            "tree": ["README.md"],
            "releases": [],
        },
        {
            "name": "pushed-lies",
            "description": "The listing date lies about this one.",
            "topics": ["stale"],
            "pushed_at": pushed,
            "commits": [commit_payload("e" * 40, old)],
            "tree": list(full_files),
            "releases": [{"tag_name": "v2.0.0"}],
        },
        {
            "name": "stale-widget",
            "description": "Nobody has touched this in a while.",
            "topics": ["widget"],
            "pushed_at": old,
            "commits": [commit_payload("f" * 40, old)],
            "tree": list(full_files),
            "releases": [{"tag_name": "v0.9.1"}],
        },
    ]
    return {"org": org, "repos": repos}


def make_rate_limit_fixtures(org="TEST-ORG"):
    """Default fixtures with bare-bones rate-limited: the refresh
    fetches aurora, then hits the limit on the second repo."""
    fixtures = make_default_fixtures(org)
    for repo in fixtures["repos"]:
        if repo["name"] == "bare-bones":
            repo["rate_limit"] = True
    return fixtures


def make_error_fixtures(org="TEST-ORG"):
    """Default fixtures with no-license-lib failing with a 500."""
    fixtures = make_default_fixtures(org)
    for repo in fixtures["repos"]:
        if repo["name"] == "no-license-lib":
            repo["error"] = 500
    return fixtures


def make_many_repos_fixtures(count, org="TEST-ORG"):
    """N minimal repos, for the pagination test."""
    repos = []
    for index in range(count):
        repos.append({
            "name": "repo-%03d" % index,
            "description": "Repo number %d." % index,
            "topics": [],
            "pushed_at": iso_days_ago(1),
            "commits": [commit_payload("%040d" % index,
                                       iso_days_ago(1))],
            "tree": ["README.md"],
            "releases": [],
        })
    return {"org": org, "repos": repos}


class _FakeState:
    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.recorded_requests = []
        self.request_counts = {}

    def count_for(self, substring):
        """Requests whose path contains the substring."""
        return sum(count for path, count in self.request_counts.items()
                   if substring in path)


def _etag_for(path):
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    return '"fake-%s"' % digest


def _listing_payload(repo, org):
    return {
        "name": repo["name"],
        "full_name": "%s/%s" % (org, repo["name"]),
        "html_url": "https://github.com/%s/%s" % (org, repo["name"]),
        "description": repo.get("description"),
        "topics": list(repo.get("topics") or []),
        "pushed_at": repo.get("pushed_at"),
    }


def _rate_limit_response():
    reset = int(datetime.now(timezone.utc).timestamp()) + 3600
    return (403, {"message": "API rate limit exceeded for 127.0.0.1."},
            {"X-RateLimit-Remaining": "0",
             "X-RateLimit-Reset": str(reset)})


def _make_handler(state):
    class FakeGitHubHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            headers = {key.lower(): value
                       for key, value in self.headers.items()}
            state.recorded_requests.append(("GET", self.path, headers))
            state.request_counts[self.path] = (
                state.request_counts.get(self.path, 0) + 1)
            status, payload, extra = self._route(path, query, headers)
            body = (json.dumps(payload).encode("utf-8")
                    if payload is not None else b"")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _etag_or_304(self, headers):
            """(etag, is_304): honor If-None-Match on 200s."""
            etag = _etag_for(self.path)
            if headers.get("if-none-match") == etag:
                return etag, True
            return etag, False

        def _route(self, path, query, headers):
            if path == "/rate_limit":
                etag, is_304 = self._etag_or_304(headers)
                if is_304:
                    return 304, None, {"ETag": etag}
                return 200, {"resources": {"core": {"remaining": 60}}}, \
                    {"ETag": etag}
            match = re.match(r"^/orgs/([^/]+)/repos$", path)
            if match:
                return self._org_repos(match.group(1), query, headers)
            match = re.match(r"^/repos/([^/]+)/([^/]+)/commits$", path)
            if match:
                return self._repo_detail(match.group(2), "commits",
                                         headers)
            match = re.match(
                r"^/repos/([^/]+)/([^/]+)/git/trees/([^/]+)$", path)
            if match:
                return self._repo_detail(match.group(2), "tree",
                                         headers, match.group(3))
            match = re.match(r"^/repos/([^/]+)/([^/]+)/releases$", path)
            if match:
                return self._repo_detail(match.group(2), "releases",
                                         headers)
            return 404, {"message": "Not Found"}, {}

        def _org_repos(self, org, query, headers):
            if state.fixtures.get("rate_limit_listing"):
                return _rate_limit_response()
            if state.fixtures.get("unknown_org"):
                return 404, {"message": "Not Found"}, {}
            repos = state.fixtures["repos"]
            try:
                per_page = int(query.get("per_page", ["30"])[0])
            except ValueError:
                per_page = 30
            try:
                page = int(query.get("page", ["1"])[0])
            except ValueError:
                page = 1
            start = (page - 1) * per_page
            end = start + per_page
            items = [_listing_payload(repo, org)
                     for repo in repos[start:end]]
            etag, is_304 = self._etag_or_304(headers)
            extra = {"ETag": etag}
            if is_304:
                return 304, None, extra
            if end < len(repos):
                host = self.headers.get("Host", "127.0.0.1")
                base = "http://%s" % host
                last_page = (len(repos) + per_page - 1) // per_page
                extra["Link"] = (
                    '<%s/orgs/%s/repos?per_page=%d&page=%d>; '
                    'rel="next", <%s/orgs/%s/repos?per_page=%d&page=%d>; '
                    'rel="last"' % (base, org, per_page, page + 1,
                                    base, org, per_page, last_page))
            return 200, items, extra

        def _repo_detail(self, repo_name, kind, headers, sha=None):
            repo = None
            for candidate in state.fixtures["repos"]:
                if candidate["name"] == repo_name:
                    repo = candidate
                    break
            if repo is None:
                return 404, {"message": "Not Found"}, {}
            if repo.get("rate_limit"):
                return _rate_limit_response()
            if repo.get("forbidden"):
                return 403, {"message": "Forbidden"}, {}
            if repo.get("error"):
                return repo["error"], {"message": "Fake server error"}, {}
            if kind == "commits":
                if repo.get("commits") is None:
                    return 409, {"message": "Git Repository is empty."}, {}
                payload = list(repo["commits"])
            elif kind == "tree":
                if repo.get("commits") is None:
                    return 404, {"message": "Not Found"}, {}
                payload = {
                    "sha": sha,
                    "tree": [{"path": entry, "type": "blob",
                              "sha": "0" * 40, "size": 100}
                             for entry in repo.get("tree") or []],
                    "truncated": False,
                }
            else:  # releases
                payload = list(repo.get("releases") or [])
            etag, is_304 = self._etag_or_304(headers)
            if is_304:
                return 304, None, {"ETag": etag}
            return 200, payload, {"ETag": etag}

    return FakeGitHubHandler


def start_fake_github(fixtures):
    """Start the fake GitHub API server. Returns (server, base_url)."""
    state = _FakeState(fixtures)
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 _make_handler(state))
    server.daemon_threads = True
    server.fake_state = state
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    server.fake_thread = thread
    host, port = server.server_address
    return server, "http://%s:%d" % (host, port)


def stop_fake_github(server):
    """Stop a fake GitHub API server started by start_fake_github."""
    server.shutdown()
    server.server_close()
    server.fake_thread.join(timeout=5)
