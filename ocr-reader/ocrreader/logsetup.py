"""Wire the T21 debug log layer to OCR Reader.

make_logger returns a DebugLogger for this app: the app version
as its only setting, Tesseract as a service check (present or
not, with its version when found), and no network services (this
app has no network). No secrets ever reach the log or the
report: nothing the reader handles is secret.

The log dir is computed here, not in settings, so the CLI can
use the logger without importing the GUI's settings module:
$XDG_DATA_HOME/ocr-reader/logs, or ~/.local/share/ocr-reader/logs.
"""

import os
import shutil
import subprocess

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


def _tesseract_status():
    """Tesseract presence for the debug report (never raises)."""
    path = shutil.which("tesseract")
    if path is None:
        return "not installed (sudo apt install tesseract-ocr)"
    try:
        proc = subprocess.run(
            ["tesseract", "--version"], capture_output=True,
            text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "installed but would not answer (%s)" % exc
    first = proc.stdout.splitlines()[0] if proc.stdout else ""
    return "installed (%s)" % first if first else "installed"


def make_logger(log_dir_path=None):
    """The debug log layer, wired to this app."""
    logger = DebugLogger(APP_SLUG, __version__,
                         log_dir=log_dir_path or log_dir())
    logger.set_setting("app_version", __version__)
    logger.register_service("Tesseract", _tesseract_status)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger
