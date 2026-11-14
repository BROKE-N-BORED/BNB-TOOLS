"""Settings for OCR Reader.

A small JSON store under the user's data dir. It holds the last
folder read from and the default OCR language. It is NOT Qt
QSettings: the GUI keeps its own geometry in QSettings, and this
store stays dependency-free so the CLI works without Qt.

data_dir() and log_dir() return the same paths as
ocrreader.logsetup: $XDG_DATA_HOME/ocr-reader, or
~/.local/share/ocr-reader. A test pins that agreement, so the
two modules can never drift apart.
"""

import json
import os
import tempfile

DATA_DIR_NAME = "ocr-reader"
DEFAULT_LANGUAGE = "eng"


def data_dir():
    """Where settings and logs live."""
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return os.path.join(base, DATA_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share",
                        DATA_DIR_NAME)


def default_settings_path():
    return os.path.join(data_dir(), "settings.json")


def log_dir():
    """Where the debug log lives (next to the settings)."""
    return os.path.join(data_dir(), "logs")


class Settings:
    """The last folder read from and the default OCR language.

    Loading tolerates a missing or corrupt file (defaults win, no
    crash). Saving is atomic: temp file + os.replace.
    """

    def __init__(self, path=None):
        self.path = path or default_settings_path()
        self.last_folder = None
        self.language = DEFAULT_LANGUAGE
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
        if isinstance(data.get("language"), str) and data[
                "language"]:
            self.language = data["language"]

    def save(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = {
            "last_folder": self.last_folder,
            "language": self.language,
        }
        fd, tmp = tempfile.mkstemp(prefix=".ocrreader-settings-",
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
