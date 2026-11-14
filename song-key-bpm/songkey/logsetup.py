"""Wire the T21 debug log layer to Song Key BPM.

make_logger returns a DebugLogger for this app: the app version
as its only setting, the DSP dependencies (aubio, miniaudio,
numpy) as version checks, and no services (this app has no
network and no services). No secrets ever reach the log or the
report: nothing the analyzer handles is secret.
"""

from . import APP_SLUG, __version__
from .debug_log import DebugLogger
from .settings import log_dir


def make_logger(log_dir_path=None):
    """The debug log layer, wired to this app."""
    logger = DebugLogger(APP_SLUG, __version__,
                         log_dir=log_dir_path or log_dir())
    logger.register_dependency("aubio")
    logger.register_dependency("miniaudio")
    logger.register_dependency("numpy")
    logger.set_setting("app_version", __version__)
    logger.register_service(
        "network and services",
        lambda: "none: this app has no network and no services")
    return logger
