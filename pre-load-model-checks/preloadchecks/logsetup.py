"""Wire the T21 debug log layer to Pre-Load Model Checks.

make_logger returns a DebugLogger for this app: the app version
as its only setting, /proc and memory as service checks, and no
network services (this app has no network). No secrets ever
reach the log or the report: nothing this tool handles is
secret.

The log dir is computed here, not in a settings module, so the
CLI can use the logger without importing the GUI:
$XDG_DATA_HOME/pre-load-model-checks/logs, or
~/.local/share/pre-load-model-checks/logs.
"""

import os

from . import APP_SLUG, __version__
from .debug_log import DebugLogger
from . import processes as proc_mod
from . import ram as ram_mod


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


def _process_status():
    """How many processes are visible (never raises)."""
    try:
        found = proc_mod.collect(sample_interval=0)
    except OSError as exc:
        return "cannot read the process list (%s)" % exc
    return "%d processes visible" % len(found)


def _memory_status():
    """Free RAM for the debug report (never raises)."""
    try:
        free = ram_mod.available_bytes()
        total = ram_mod.total_bytes()
    except OSError as exc:
        return "cannot read the memory info (%s)" % exc
    return "%s free of %s total" % (ram_mod.format_gb(free),
                                    ram_mod.format_gb(total))


def make_logger(log_dir_path=None):
    """The debug log layer, wired to this app."""
    logger = DebugLogger(APP_SLUG, __version__,
                         log_dir=log_dir_path or log_dir())
    logger.set_setting("app_version", __version__)
    logger.register_service("Process list", _process_status)
    logger.register_service("Memory", _memory_status)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger
