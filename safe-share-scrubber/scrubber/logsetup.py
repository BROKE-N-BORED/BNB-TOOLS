"""Logger setup for Safe Share Scrubber.

make_logger lives here so the GUI can import the logger without
importing the CLI. This module imports only debug_log, settings,
and the package version: no core, no report, no cli.
"""

from . import __version__
from .debug_log import DebugLogger
from .settings import log_dir


def make_logger():
    """The debug log layer, wired to this app.

    Settings: the app version only, no secrets ever. Services: none
    to check, this app has no network and no services, and the
    context snapshot says so plainly.
    """
    logger = DebugLogger("safe-share-scrubber", __version__,
                         log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.set_setting("app_version", __version__)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger
