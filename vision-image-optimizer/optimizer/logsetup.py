"""The debug log layer, wired to this app's services + settings."""

from . import __version__
from .debug_log import DebugLogger, check_ollama
from .settings import Settings, log_dir


def make_logger(settings=None):
    """The debug log layer, wired to this app's services + settings."""
    logger = DebugLogger("vision-image-optimizer", __version__,
                         log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.register_dependency("Pillow")
    if settings is None:
        settings = Settings()
    for key, value in settings.all_values().items():
        logger.set_setting(key, value)
    url = settings.get("ollama_url")
    logger.register_service("ollama",
                            lambda: check_ollama(url, timeout=2))
    return logger
