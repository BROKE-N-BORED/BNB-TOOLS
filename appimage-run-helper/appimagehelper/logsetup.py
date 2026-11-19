"""Wire the T21 debug log layer to AppImage Runner.

make_logger returns a DebugLogger for this app: the app version
as its only setting, FUSE as a service check (AppImages need the
FUSE library to mount; a missing fusermount is the first thing
to check when an AppImage will not start), and no network
services (this app has no network). No secrets ever reach the
log or the report: nothing the runner handles is secret.

The log dir is computed here, not in settings, so the CLI can
use the logger without importing the GUI's settings module:
$XDG_DATA_HOME/appimage-run-helper/logs, or
~/.local/share/appimage-run-helper/logs.
"""

import os
import shutil

from . import APP_SLUG, __version__
from .debug_log import DebugLogger


def data_dir():
    """The app data dir, honoring XDG_DATA_HOME."""
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return os.path.join(base, APP_SLUG)
    return os.path.join(os.path.expanduser("~"), ".local", "share",
                        APP_SLUG)


def log_dir():
    """The debug log dir."""
    return os.path.join(data_dir(), "logs")


def _fuse_status():
    """FUSE presence for the debug report (never raises)."""
    for name in ("fusermount3", "fusermount"):
        path = shutil.which(name)
        if path is not None:
            return "installed (%s)" % path
    return ("not found: some AppImages need the FUSE library "
            "(libfuse2) to start")


def make_logger(log_dir_path=None):
    """The debug log layer, wired to this app."""
    logger = DebugLogger(APP_SLUG, __version__,
                         log_dir=log_dir_path or log_dir())
    logger.set_setting("app_version", __version__)
    logger.register_service("FUSE (AppImage mounting)",
                            _fuse_status)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger
