"""JSON cache for Repo Health Board.

One file holding the org, the last fetch time, per-repo detail
dicts keyed by repo name, and ETags per URL path. Loading
tolerates a missing or corrupt file (starts empty, no crash).
Saving is atomic: temp file + os.replace.
"""

import json
import os
import tempfile


def _empty_data():
    return {"version": 1, "org": None, "fetched_at": None,
            "repos": {}, "etags": {}}


class BoardCache:
    """The board cache, backed by one JSON file."""

    def __init__(self, path):
        self.path = path
        self._data = _empty_data()
        self.load()

    def load(self):
        """Read the file. Missing or corrupt starts empty, no crash."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("cache is not an object")
            repos = data.get("repos") or {}
            etags = data.get("etags") or {}
            if not isinstance(repos, dict):
                repos = {}
            if not isinstance(etags, dict):
                etags = {}
            self._data = {
                "version": 1,
                "org": data.get("org"),
                "fetched_at": data.get("fetched_at"),
                "repos": repos,
                "etags": etags,
            }
        except (OSError, ValueError):
            self._data = _empty_data()

    def save(self):
        """Write the file atomically (temp file + os.replace)."""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".board-cache-",
                                   dir=parent or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @property
    def org(self):
        return self._data.get("org")

    @org.setter
    def org(self, value):
        self._data["org"] = value

    @property
    def fetched_at(self):
        return self._data.get("fetched_at")

    @fetched_at.setter
    def fetched_at(self, value):
        self._data["fetched_at"] = value

    def get_repo(self, name):
        """The cached detail dict for a repo, or None."""
        detail = self._data["repos"].get(name)
        return dict(detail) if isinstance(detail, dict) else None

    def set_repo(self, name, detail):
        """Store a repo detail dict (a RepoHealth.to_dict())."""
        self._data["repos"][name] = dict(detail)

    def repo_names(self):
        """Cached repo names, sorted."""
        return sorted(self._data["repos"])

    def get_etag(self, path):
        """The cached ETag for a URL path, or None."""
        return self._data["etags"].get(path)

    def set_etag(self, path, etag):
        """Store the ETag the server sent for a URL path."""
        self._data["etags"][path] = etag
