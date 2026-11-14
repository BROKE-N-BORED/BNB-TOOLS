"""Repo health data and flag rules for Repo Health Board.

Flag rules (exact):

- placeholder: the fetched tree has no file outside scaffolding.
  Scaffolding is README* / LICENSE* (any file whose basename starts
  with "readme" or "license"/"licence", case-insensitive),
  .gitignore, SECURITY.md, .gitattributes, and anything under
  .github/. An empty repo (tree fetched, zero files) is a
  placeholder. A repo whose tree was NOT fetched (file_count None)
  is never flagged placeholder: unknown is not empty.
- missing README / missing LICENSE / missing .gitignore /
  missing SECURITY.md: judged from tree_paths. Any path whose
  basename matches, case-insensitive, counts as present (so a
  README under docs/ counts). Only judged when the tree was
  fetched; an unfetched tree earns no missing-file flags.
- missing description: description empty or null.
- missing topics: topics empty.
- stale: the last real commit (last_commit_date, from the commits
  endpoint) is older than STALE_DAYS (90). A repo with no known
  commit date is not flagged stale: unknown is not stale.

Suite status is NOT a flag kind. suite_status() is a separate
field: "has CI" when any tree path is under .github/workflows/
ending .yml/.yaml, "no CI file" when the tree was fetched and has
none, "unknown" when the tree was not fetched. It is never a
pass/fail claim: it says only whether a CI file exists.

pushed_at (the listing date) is NEVER used by any rule. It exists
on RepoHealth only so tests can prove the board shows the real
commit date when the listing date disagrees, and so the refresh
pass can tell whether a cached detail is still current.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

STALE_DAYS = 90

SCAFFOLD_EXACT_BASENAMES = (".gitignore", "security.md", ".gitattributes")


def parse_github_date(value):
    """Parse a GitHub ISO date ("2026-11-14T12:00:00Z") to a
    timezone-aware datetime, or None when it does not parse."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _basename(path):
    return os.path.basename(path).lower()


def _is_readme(path):
    return _basename(path).startswith("readme")


def _is_license(path):
    name = _basename(path)
    return name.startswith("license") or name.startswith("licence")


def _is_scaffolding(path):
    """True when a tree path is scaffolding, not real content."""
    lowered = path.lower()
    if lowered.startswith(".github/"):
        return True
    if _is_readme(path) or _is_license(path):
        return True
    return _basename(path) in SCAFFOLD_EXACT_BASENAMES


@dataclass
class Flag:
    """One health flag: a stable kind plus a plain-words label."""

    kind: str
    label: str


@dataclass
class RepoHealth:
    """Everything the board knows about one repo.

    pushed_at is the listing date, kept for comparison only (see
    the module docstring). last_commit_date is the real date from
    the commits endpoint, or None when unknown. file_count is None
    when the tree was not fetched; tree_paths is empty then too.
    """

    name: str
    html_url: str = ""
    description: str = None
    topics: list = field(default_factory=list)
    pushed_at: str = None
    last_commit_date: str = None
    last_commit_sha: str = None
    file_count: int = None
    tree_paths: list = field(default_factory=list)
    latest_release_tag: str = None
    fetched_at: str = ""
    from_cache: bool = False

    def to_dict(self):
        """Plain dict for the cache. from_cache is not stored: a
        detail read back from the cache is from the cache by
        definition, and the refresh pass sets the flag."""
        return {
            "name": self.name,
            "html_url": self.html_url,
            "description": self.description,
            "topics": list(self.topics or []),
            "pushed_at": self.pushed_at,
            "last_commit_date": self.last_commit_date,
            "last_commit_sha": self.last_commit_sha,
            "file_count": self.file_count,
            "tree_paths": list(self.tree_paths or []),
            "latest_release_tag": self.latest_release_tag,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data):
        """Build from a cache dict. Tolerates missing keys."""
        data = data or {}
        return cls(
            name=data.get("name") or "",
            html_url=data.get("html_url") or "",
            description=data.get("description"),
            topics=list(data.get("topics") or []),
            pushed_at=data.get("pushed_at"),
            last_commit_date=data.get("last_commit_date"),
            last_commit_sha=data.get("last_commit_sha"),
            file_count=data.get("file_count"),
            tree_paths=list(data.get("tree_paths") or []),
            latest_release_tag=data.get("latest_release_tag"),
            fetched_at=data.get("fetched_at") or "",
            from_cache=False,
        )


def compute_flags(health, now=None):
    """The flags for one repo, in a fixed order.

    now is the reference time (default: now, UTC); tests pass it
    to pin the stale boundary. pushed_at is never consulted.
    """
    flags = []
    tree_known = health.file_count is not None
    if tree_known:
        paths = list(health.tree_paths or [])
        if not any(not _is_scaffolding(path) for path in paths):
            flags.append(Flag("placeholder", "placeholder"))
        if not any(_is_readme(path) for path in paths):
            flags.append(Flag("missing-readme", "no README"))
        if not any(_is_license(path) for path in paths):
            flags.append(Flag("missing-license", "no LICENSE"))
        if not any(_basename(path) == ".gitignore" for path in paths):
            flags.append(Flag("missing-gitignore", "no .gitignore"))
        if not any(_basename(path) == "security.md" for path in paths):
            flags.append(Flag("missing-security", "no SECURITY.md"))
    if not (health.description or "").strip():
        flags.append(Flag("missing-description", "no description"))
    if not health.topics:
        flags.append(Flag("missing-topics", "no topics"))
    commit_date = parse_github_date(health.last_commit_date)
    if commit_date is not None:
        reference = now or datetime.now(timezone.utc)
        if reference - commit_date > timedelta(days=STALE_DAYS):
            flags.append(
                Flag("stale", "stale (no commit in 90 days)"))
    return flags


def suite_status(health):
    """CI file status: "has CI", "no CI file", or "unknown".

    This says only whether a workflow file exists under
    .github/workflows/. It is never a pass/fail claim.
    """
    if health.file_count is None:
        return "unknown"
    for path in health.tree_paths or []:
        lowered = path.lower()
        if lowered.startswith(".github/workflows/") and (
                lowered.endswith(".yml") or lowered.endswith(".yaml")):
            return "has CI"
    return "no CI file"
