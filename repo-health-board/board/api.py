"""GitHub API client for Repo Health Board.

Standard library only (urllib). NO AUTHENTICATION, EVER: the board
reads public repos, which need no token. Sending an Authorization
header is a defect, and a test proves none is sent on any request.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = "Repo Health Board/%s" % __version__
ACCEPT = "application/vnd.github+json"


class ApiError(Exception):
    """A GitHub API failure.

    status: HTTP status code, or None when the request never got a
    response (network failure). reset_at: epoch seconds from the
    X-RateLimit-Reset header, or None when the server sent none.
    """

    def __init__(self, status, message, reset_at=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.reset_at = reset_at


class RateLimitError(ApiError):
    """A 403 (or 429) that is a rate-limit response.

    A 403 that is NOT a rate limit is a plain ApiError.
    """


def _lower_headers(headers):
    """Response headers as a dict with lowercase keys."""
    if headers is None:
        return {}
    return {key.lower(): value for key, value in headers.items()}


def _message_from_body(body, status):
    """The GitHub error message from a response body, or a fallback."""
    if body:
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])
        text = body.strip()
        if text:
            return text[:200]
    return "GitHub returned HTTP %s" % status


def _reset_from_headers(headers):
    """Epoch seconds from X-RateLimit-Reset, or None."""
    raw = headers.get("x-ratelimit-reset")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_rate_limit(status, headers, message):
    """True when this failure is a rate-limit response."""
    if status == 429:
        return True
    if status != 403:
        return False
    if headers.get("x-ratelimit-remaining") == "0":
        return True
    lowered = (message or "").lower()
    return "rate limit" in lowered or "rate-limit" in lowered


def _next_link(headers):
    """The rel=next URL from a Link header, or None."""
    link = headers.get("link")
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip().strip("<>")
        rel = ";".join(segments[1:])
        if 'rel="next"' in rel:
            return url
    return None


def _path_from_url(url):
    """The path + query of a URL, for following a Link header."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    return path


def _quote(segment):
    return urllib.parse.quote(str(segment), safe="")


class GitHubClient:
    """Minimal GitHub API client. No auth, no token, ever.

    last_headers maps each requested path to the lowercased headers
    of its most recent response, so the refresh pass can pick up
    ETags the server sent. Headers are returned lowercased by
    get_json too.
    """

    def __init__(self, base_url="https://api.github.com", timeout=15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_headers = {}

    def get_json(self, path, etag=None):
        """GET one path. Returns (status, parsed_json_or_None, headers).

        Sends Accept and a User-Agent naming the app. Sends NO
        Authorization header, ever. A 304 returns (304, None,
        headers). HTTP failures raise ApiError (RateLimitError for
        a rate-limit response); network failures raise ApiError
        with status None.
        """
        url = self.base_url + path
        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", ACCEPT)
        request.add_header("User-Agent", USER_AGENT)
        if etag:
            request.add_header("If-None-Match", etag)
        try:
            with urllib.request.urlopen(request,
                                        timeout=self.timeout) as resp:
                headers = _lower_headers(resp.headers)
                self.last_headers[path] = headers
                if resp.status == 304:
                    return 304, None, headers
                body = resp.read().decode("utf-8")
                parsed = json.loads(body) if body.strip() else None
                return resp.status, parsed, headers
        except urllib.error.HTTPError as exc:
            headers = _lower_headers(exc.headers)
            self.last_headers[path] = headers
            if exc.code == 304:
                return 304, None, headers
            body = exc.read().decode("utf-8", "replace")
            message = _message_from_body(body, exc.code)
            reset_at = _reset_from_headers(headers)
            if _is_rate_limit(exc.code, headers, message):
                raise RateLimitError(exc.code, message, reset_at)
            raise ApiError(exc.code, message, reset_at)
        except urllib.error.URLError as exc:
            raise ApiError(
                None, "could not reach GitHub: %s" % exc.reason)


def fetch_org_repos(client, org):
    """Every repo in the org, following pagination (per_page=100)."""
    repos = []
    path = "/orgs/%s/repos?per_page=100" % _quote(org)
    while path:
        status, payload, headers = client.get_json(path)
        if status != 200 or not isinstance(payload, list):
            raise ApiError(status, "unexpected response listing repos")
        repos.extend(payload)
        nxt = _next_link(headers)
        path = _path_from_url(nxt) if nxt else None
    return repos


def fetch_latest_commit(client, owner, repo):
    """The latest commit as {"sha":..., "date":...}, or None when the
    repo has no commits (409 from GitHub, or an empty list)."""
    path = "/repos/%s/%s/commits?per_page=1" % (_quote(owner),
                                                _quote(repo))
    try:
        status, payload, _headers = client.get_json(path)
    except ApiError as exc:
        if exc.status == 409:
            return None
        raise
    if status != 200 or not payload:
        return None
    entry = payload[0]
    commit = entry.get("commit") or {}
    committer = commit.get("committer") or {}
    author = commit.get("author") or {}
    date = committer.get("date") or author.get("date")
    return {"sha": entry.get("sha"), "date": date}


def fetch_tree(client, owner, repo, sha):
    """The recursive tree payload for a commit.

    An empty repo (no sha, or a 404/409 from GitHub) returns an
    empty tree payload instead of raising.
    """
    if not sha:
        return {"sha": None, "tree": [], "truncated": False}
    path = "/repos/%s/%s/git/trees/%s?recursive=1" % (
        _quote(owner), _quote(repo), _quote(sha))
    try:
        status, payload, _headers = client.get_json(path)
    except ApiError as exc:
        if exc.status in (404, 409):
            return {"sha": sha, "tree": [], "truncated": False}
        raise
    if status != 200 or not isinstance(payload, dict):
        return {"sha": sha, "tree": [], "truncated": False}
    return payload


def fetch_latest_release(client, owner, repo):
    """The latest release as {"tag":...}, or None when there is none
    (empty list, or a 404 when releases are unavailable)."""
    path = "/repos/%s/%s/releases?per_page=1" % (_quote(owner),
                                                 _quote(repo))
    try:
        status, payload, _headers = client.get_json(path)
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    if status != 200 or not payload:
        return None
    tag = payload[0].get("tag_name")
    return {"tag": tag} if tag else None
