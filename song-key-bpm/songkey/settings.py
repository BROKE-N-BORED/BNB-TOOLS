"""Settings for Song Key BPM.

A small JSON store under the user's data dir. It holds the last
folder analyzed and the last export format used. It is NOT Qt
QSettings: the GUI keeps its own geometry in QSettings, and this
store stays dependency-free so the CLI works without Qt.
"""

import json
import os
import tempfile

DATA_DIR_NAME = "song-key-bpm"
DEFAULT_EXPORT_FORMAT = "both"


def data_dir():
    """Where settings and logs live."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share")
    return os.path.join(base, DATA_DIR_NAME)


def default_settings_path():
    return os.path.join(data_dir(), "settings.json")


def log_dir():
    """Where the debug log lives (next to the settings)."""
    return os.path.join(data_dir(), "logs")


class Settings:
    """The last folder analyzed and the last export format.

    Loading tolerates a missing or corrupt file (defaults win, no
    crash). Saving is atomic: temp file + os.replace.
    """

    def __init__(self, path=None):
        self.path = path or default_settings_path()
        self.last_folder = None
        self.export_format = DEFAULT_EXPORT_FORMAT
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("settings is not an object")
        except (OSError, ValueError):
            return
        if isinstance(data.get("last_folder"), str) and data[
                "last_folder"]:
            self.last_folder = data["last_folder"]
        if data.get("export_format") in ("csv", "json", "both"):
            self.export_format = data["export_format"]

    def save(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = {
            "last_folder": self.last_folder,
            "export_format": self.export_format,
        }
        fd, tmp = tempfile.mkstemp(prefix=".songkey-settings-",
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
