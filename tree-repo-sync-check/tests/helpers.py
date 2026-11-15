"""Shared test helpers: a fake GitHub API server and fixtures.

The fake server runs on 127.0.0.1 on an ephemeral port and serves
canned repo trees for the one endpoint the tool uses:
GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
plus /rate_limit for the debug report's service check. No test
touches the live GitHub API.

Public API:
    start_fake_github(fixtures) -> (server, base_url)
    stop_fake_github(server)
    tree_from_files(mapping) -> {path: blob SHA}
    make_repo_fixtures(...) -> fixtures dict

The server records every request on server.fake_state:
    recorded_requests: list of (method, path, headers dict with
        lowercase keys), for the no-Authorization-header test.
    request_counts: path -> number of times it was requested.

A repo fixture is a dict keyed by "owner/repo":
    branches: {branch name: {path: blob SHA}} (default branch
        "main" when only "tree" is given)
    tree: {path: blob SHA} for the default branch (shorthand)
    mode: one of "ok" (default), "notfound", "rate_limit",
        "rate_limit_no_reset", "forbidden", "error", "truncated",
        "bad_json", "no_tree"
    error_status: HTTP status for mode "error" (default 500)
    reset: epoch seconds for the rate-limit reset header
        (default: a fixed time, 2030-01-01T00:00:00Z)

Fake secrets, built from parts (concatenation), never written as
one literal: a full secret-shaped literal in a file trips secret
scanners on push, even with FAKE in it. The tool itself needs no
tokens at all; this exists only for the scrub test.
"""

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from tree_repo_sync_check import blob_sha  # noqa: E402

FAKE_GITHUB = "ghp_" + "FAKE" * 9

# Fixed reset time for rate-limit fixtures: 2030-01-01T00:00:00Z.
# A fixed time keeps the assertion exact instead of clock-based.
FIXED_RESET_EPOCH = 1893456000
FIXED_RESET_TEXT = "2030-01-01T00:00:00Z"


def tree_from_files(mapping):
    """{path: blob SHA} from {path: bytes or str} file contents."""
    tree = {}
    for path, content in mapping.items():
        if isinstance(content, str):
            content = content.encode("utf-8")
        tree[path] = blob_sha(content)
    return tree


def make_repo_fixtures(repos):
    """Wrap a {owner/repo: repo fixture} dict for the server."""
    return {"repos": repos}


def _rate_limit_headers(reset):
    headers = {"X-RateLimit-Remaining": "0"}
    if reset is not None:
        headers["X-RateLimit-Reset"] = str(reset)
    return headers


def _make_handler(state):
    class FakeGitHubHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            headers = {key.lower(): value
                       for key, value in self.headers.items()}
            state.recorded_requests.append(("GET", self.path, headers))
            state.request_counts[self.path] = (
                state.request_counts.get(self.path, 0) + 1)
            status, payload, extra, raw = self._route(path)
            if raw is not None:
                body = raw
            elif payload is not None:
                body = json.dumps(payload).encode("utf-8")
            else:
                body = b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _route(self, path):
            if path == "/rate_limit":
                return 200, {"resources": {"core": {"remaining": 60}}}, \
                    {}, None
            match = re.match(
                r"^/repos/([^/]+)/([^/]+)/git/trees/(.+)$", path)
            if match:
                owner, repo, branch = match.groups()
                branch = _unquote(branch)
                return self._tree(owner, repo, branch)
            return 404, {"message": "Not Found"}, {}, None

        def _tree(self, owner, repo, branch):
            key = "%s/%s" % (owner, repo)
            fixture = state.fixtures["repos"].get(key)
            if fixture is None:
                return 404, {"message": "Not Found"}, {}, None
            mode = fixture.get("mode", "ok")
            if mode == "notfound":
                return 404, {"message": "Not Found"}, {}, None
            if mode == "rate_limit":
                reset = fixture.get("reset", FIXED_RESET_EPOCH)
                return 403, {"message": "API rate limit exceeded."}, \
                    _rate_limit_headers(reset), None
            if mode == "rate_limit_no_reset":
                return 403, {"message": "API rate limit exceeded."}, \
                    {"X-RateLimit-Remaining": "0"}, None
            if mode == "forbidden":
                return 403, {"message": "Forbidden"}, {}, None
            if mode == "error":
                status = fixture.get("error_status", 500)
                return status, {"message": "Fake server error"}, \
                    {}, None
            if mode == "truncated":
                return 200, {"sha": branch, "tree": [],
                             "truncated": True}, {}, None
            if mode == "bad_json":
                return 200, None, {}, b"{not json"
            if mode == "no_tree":
                return 200, {"sha": branch}, {}, None
            branches = fixture.get("branches")
            if branches is None:
                branches = {"main": fixture.get("tree") or {}}
            if branch not in branches:
                return 404, {"message": "Not Found"}, {}, None
            entries = []
            for path in sorted(branches[branch]):
                entries.append({"path": path, "type": "blob",
                                "sha": branches[branch][path],
                                "size": 100})
            for extra in fixture.get("extra_entries") or []:
                entries.append(dict(extra))
            payload = {"sha": branch, "tree": entries,
                       "truncated": False}
            return 200, payload, {}, None

    return FakeGitHubHandler


def _unquote(text):
    from urllib.parse import unquote
    return unquote(text)


class _FakeState:
    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.recorded_requests = []
        self.request_counts = {}

    def total_requests(self):
        return sum(self.request_counts.values())


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
