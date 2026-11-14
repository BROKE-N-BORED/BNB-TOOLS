"""The refresh pass for Repo Health Board.

Two passes over the org:

1. List the org repos (1-2 calls, paginated).
2. Per repo, in name order: when the cached detail's pushed_at
   matches the fresh listing's pushed_at, reuse the cached detail
   (no detail calls); otherwise fetch the latest commit, the tree,
   and the latest release (3 calls), compute file_count from the
   tree, and store the detail in the cache with any ETags the
   server sent.

refresh_org never raises. A rate limit stops the pass cleanly:
everything fetched so far plus cached rows is kept, the rest are
marked unchecked, and rate_limited + rate_reset_at are set. A
cancel does the same clean stop with no error. A per-repo error
(not a rate limit) records the message, keeps the cached row when
one exists, and moves on to the next repo.
"""

import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .api import (ApiError, RateLimitError, fetch_latest_commit,
                  fetch_latest_release, fetch_org_repos, fetch_tree)
from .flags import RepoHealth


@dataclass
class RefreshResult:
    """What a refresh produced."""

    rows: list
    fresh_count: int = 0
    cached_count: int = 0
    unchecked_count: int = 0
    rate_limited: bool = False
    rate_reset_at: int = None
    errors: list = field(default_factory=list)


def _unchecked_row(listing, fetched_at):
    """A row for a repo that could not be checked: listing fields
    only, every fetched field None."""
    return RepoHealth(
        name=listing.get("name") or "",
        html_url=listing.get("html_url") or "",
        description=listing.get("description"),
        topics=list(listing.get("topics") or []),
        pushed_at=listing.get("pushed_at"),
        last_commit_date=None,
        last_commit_sha=None,
        file_count=None,
        tree_paths=[],
        latest_release_tag=None,
        fetched_at=fetched_at,
        from_cache=False,
    )


def _fetch_repo_detail(client, org, listing, fetched_at):
    """Three calls per repo: latest commit, tree, latest release."""
    name = listing.get("name") or ""
    commit = fetch_latest_commit(client, org, name)
    sha = commit["sha"] if commit else None
    tree = fetch_tree(client, org, name, sha)
    release = fetch_latest_release(client, org, name)
    entries = tree.get("tree") or []
    blobs = [entry for entry in entries
             if entry.get("type") == "blob"]
    paths = [entry.get("path") for entry in blobs
             if entry.get("path")]
    return RepoHealth(
        name=name,
        html_url=listing.get("html_url") or "",
        description=listing.get("description"),
        topics=list(listing.get("topics") or []),
        pushed_at=listing.get("pushed_at"),
        last_commit_date=commit["date"] if commit else None,
        last_commit_sha=sha,
        file_count=len(blobs),
        tree_paths=paths,
        latest_release_tag=release["tag"] if release else None,
        fetched_at=fetched_at,
        from_cache=False,
    )


def _store_etags(client, cache, org, name, health):
    """Keep the ETags the server sent for this repo's detail
    calls, read back from the client's last response headers."""
    quote = urllib.parse.quote
    paths = [
        "/repos/%s/%s/commits?per_page=1" % (quote(org, safe=""),
                                             quote(name, safe="")),
        "/repos/%s/%s/releases?per_page=1" % (quote(org, safe=""),
                                              quote(name, safe="")),
    ]
    if health.last_commit_sha:
        paths.append(
            "/repos/%s/%s/git/trees/%s?recursive=1"
            % (quote(org, safe=""), quote(name, safe=""),
               quote(health.last_commit_sha, safe="")))
    for path in paths:
        headers = client.last_headers.get(path) or {}
        etag = headers.get("etag")
        if etag:
            cache.set_etag(path, etag)


def refresh_org(client, org, cache, progress_cb=None, cancel=None):
    """Refresh every repo in the org. Never raises.

    progress_cb(kind, current, total, name) reports progress;
    kind is "listing" at the start, "repo" per repo, and "done"
    at a clean finish. cancel is a callable returning bool; when
    it returns True the pass stops cleanly with no error.
    """
    result = RefreshResult(rows=[])
    fetched_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds")

    def progress(kind, current, total, name):
        if progress_cb is not None:
            progress_cb(kind, current, total, name)

    def cancelled():
        return bool(cancel is not None and cancel())

    progress("listing", 0, 0, org)
    try:
        listings = fetch_org_repos(client, org)
    except RateLimitError as exc:
        result.rate_limited = True
        result.rate_reset_at = exc.reset_at
        result.errors.append(
            "GitHub rate limit hit while listing repos: %s"
            % exc.message)
        return result
    except ApiError as exc:
        result.errors.append(
            "could not list repos: %s" % exc.message)
        return result
    listings = sorted(listings,
                      key=lambda item: (item.get("name") or "").lower())
    total = len(listings)
    stopped_early = False
    for index, listing in enumerate(listings, start=1):
        name = listing.get("name") or ""
        progress("repo", index, total, name)
        if cancelled():
            # Same clean stop as a rate limit, with no error.
            stopped_early = True
            for rest in listings[index - 1:]:
                result.rows.append(_unchecked_row(rest, fetched_at))
                result.unchecked_count += 1
            break
        cached = cache.get_repo(name)
        if cached and cached.get("pushed_at") == listing.get(
                "pushed_at"):
            health = RepoHealth.from_dict(cached)
            health.from_cache = True
            result.rows.append(health)
            result.cached_count += 1
            continue
        try:
            health = _fetch_repo_detail(client, org, listing,
                                        fetched_at)
        except RateLimitError as exc:
            result.rate_limited = True
            result.rate_reset_at = exc.reset_at
            result.errors.append(
                "GitHub rate limit hit on %s: %s"
                % (name, exc.message))
            stopped_early = True
            for rest in listings[index - 1:]:
                result.rows.append(_unchecked_row(rest, fetched_at))
                result.unchecked_count += 1
            break
        except (ApiError, Exception) as exc:  # one repo never kills
            # the refresh; keep the cached row when one exists.
            if isinstance(exc, ApiError):
                message = exc.message
            else:
                message = str(exc)
            result.errors.append("%s: %s" % (name, message))
            if cached:
                health = RepoHealth.from_dict(cached)
                health.from_cache = True
                result.rows.append(health)
                result.cached_count += 1
            else:
                result.rows.append(_unchecked_row(listing, fetched_at))
                result.unchecked_count += 1
            continue
        cache.set_repo(name, health.to_dict())
        _store_etags(client, cache, org, name, health)
        result.rows.append(health)
        result.fresh_count += 1
    if not stopped_early:
        progress("done", total, total, "")
    cache.org = org
    cache.fetched_at = fetched_at
    try:
        cache.save()
    except OSError as exc:
        result.errors.append("could not save the cache: %s" % exc)
    return result
