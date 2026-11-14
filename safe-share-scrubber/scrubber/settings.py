"""Settings for Safe Share Scrubber.

Only what the app needs: the config, cache, and log folders, and
window geometry memory (U5). No behaviour settings exist: the app
has nothing for the user to configure. The folder helpers work
without Qt so the CLI runs on a machine without it.
"""

import os

try:
    from PySide6.QtCore import QSettings, QStandardPaths
    _HAVE_QT = True
except ImportError:  # pragma: no cover - CLI without Qt
    _HAVE_QT = False
    QSettings = None
    QStandardPaths = None

ORG_NAME = "BrokeNBored"
APP_NAME = "SafeShareScrubber"
CONFIG_DIR_NAME = "safe-share-scrubber"


def config_dir():
    """Where settings and logs live.

    Generic locations, not ConfigLocation: the plain locations
    append the Qt application name, which differs between the GUI
    (set in run_gui), the CLI (no application instance), and any
    helper process, so the same app would scatter its folders.
    The folder name below is already app-specific.
    """
    if _HAVE_QT:
        path = QStandardPaths.writableLocation(
            QStandardPaths.GenericConfigLocation)
        if path:
            return os.path.join(path, CONFIG_DIR_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config")
    return os.path.join(base, CONFIG_DIR_NAME)


def cache_dir():
    """Where the single-instance lock lives (see config_dir for
    why this is the generic location)."""
    if _HAVE_QT:
        path = QStandardPaths.writableLocation(
            QStandardPaths.GenericCacheLocation)
        if path:
            return os.path.join(path, CONFIG_DIR_NAME)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser(
        "~/.cache")
    return os.path.join(base, CONFIG_DIR_NAME)


def log_dir():
    """Where the debug log lives (next to the config)."""
    return os.path.join(config_dir(), "logs")


class Settings:
    """Window geometry, QSettings-backed.

    Pass a QSettings object (tests do this to isolate state). Without
    Qt, geometry is kept in memory for the run and forgotten.
    """

    def __init__(self, backend=None):
        self._qsettings = None
        self._memory = None
        if backend is not None and _HAVE_QT and isinstance(
                backend, QSettings):
            self._qsettings = backend
        elif _HAVE_QT:
            self._qsettings = QSettings(ORG_NAME, APP_NAME)

    def get_geometry(self):
        """Saved window geometry bytes, or None when never saved."""
        if self._qsettings is not None:
            from PySide6.QtCore import QByteArray
            value = self._qsettings.value("window_geometry", None)
            if isinstance(value, QByteArray):
                return bytes(value)
            return None
        return self._memory

    def set_geometry(self, data):
        """Save window geometry bytes."""
        if self._qsettings is not None:
            from PySide6.QtCore import QByteArray
            self._qsettings.setValue("window_geometry",
                                     QByteArray(data))
            self._qsettings.sync()
        else:
            self._memory = bytes(data)
