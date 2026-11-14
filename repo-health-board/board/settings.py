"""Settings for Repo Health Board.

A small JSON store under the user's data dir. It holds the org,
the last refresh time, and an optional cache path override. It is
NOT Qt QSettings: the GUI keeps its own geometry in QSettings,
and this store stays dependency-free so the CLI works without Qt.
"""

import json
import os
import tempfile

DEFAULT_ORG = "BROKE-N-BORED"
DATA_DIR_NAME = "repo-health-board"


def data_dir():
    """Where settings, cache, and logs live."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share")
    return os.path.join(base, DATA_DIR_NAME)


def default_settings_path():
    return os.path.join(data_dir(), "settings.json")


def default_cache_path():
    return os.path.join(data_dir(), "cache.json")


def default_repos_path():
    """The fetch output: repos.json in the data dir."""
    return os.path.join(data_dir(), "repos.json")


def default_flagged_path():
    """The flag output: flagged.json in the data dir."""
    return os.path.join(data_dir(), "flagged.json")


def default_board_text_path():
    """The flag text output: board.txt in the data dir."""
    return os.path.join(data_dir(), "board.txt")


def log_dir():
    """Where the debug log lives (next to the settings)."""
    return os.path.join(data_dir(), "logs")


class Settings:
    """The org, last refresh, and cache path override.

    Loading tolerates a missing or corrupt file (defaults win, no
    crash). Saving is atomic: temp file + os.replace.
    """

    def __init__(self, path=None):
        self.path = path or default_settings_path()
        self.org = DEFAULT_ORG
        self.last_refresh = None
        self.cache_path = None
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("settings is not an object")
        except (OSError, ValueError):
            return
        if isinstance(data.get("org"), str) and data["org"]:
            self.org = data["org"]
        if isinstance(data.get("last_refresh"), str):
            self.last_refresh = data["last_refresh"]
        if isinstance(data.get("cache_path"), str) and data[
                "cache_path"]:
            self.cache_path = data["cache_path"]

    def save(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = {
            "org": self.org,
            "last_refresh": self.last_refresh,
            "cache_path": self.cache_path,
        }
        fd, tmp = tempfile.mkstemp(prefix=".board-settings-",
                                   dir=parent or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def cache_file(self):
        """The cache file: the override when set, else the default."""
        return self.cache_path or default_cache_path()
