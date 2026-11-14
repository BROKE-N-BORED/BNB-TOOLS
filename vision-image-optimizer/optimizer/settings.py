"""Settings for Vision Image Optimizer.

Persisted in QSettings when Qt is available (the normal case — the
app ships PySide6), with a plain JSON file fallback so the CLI still
works on a machine without Qt. The fallback lives in the same config
folder QSettings would use.
"""

import json
import os

try:
    from PySide6.QtCore import QSettings, QStandardPaths
    _HAVE_QT = True
except ImportError:  # pragma: no cover - CLI without Qt
    _HAVE_QT = False
    QSettings = None
    QStandardPaths = None

ORG_NAME = "BrokeNBored"
APP_NAME = "VisionImageOptimizer"

DEFAULTS = {
    "size_preset": "512w",
    "custom_width": 512,
    "quality_preset": "85",
    "custom_quality": 85,
    "output_format": "JPEG",
    "output_folder": "",
    "ollama_url": "http://127.0.0.1:11434",
    "fast_model": "minicpm-v",
    "smart_model": "qwen3-vl:2b-instruct",
    "prompt": ("Describe this image in plain words. Say what is in "
               "it and what stands out."),
    "cache_enabled": True,
}

SIZE_PRESETS = ("512w", "768w", "1024w", "Original", "Custom")
QUALITY_PRESETS = ("60", "75", "85", "95", "Custom")


def config_dir():
    """Where settings live (QStandardPaths when Qt is here)."""
    if _HAVE_QT:
        path = QStandardPaths.writableLocation(
            QStandardPaths.ConfigLocation)
        if path:
            return os.path.join(path, "vision-image-optimizer")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config")
    return os.path.join(base, "vision-image-optimizer")


def cache_dir():
    """Where the image/description cache lives."""
    if _HAVE_QT:
        path = QStandardPaths.writableLocation(
            QStandardPaths.CacheLocation)
        if path:
            return os.path.join(path, "vision-image-optimizer")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser(
        "~/.cache")
    return os.path.join(base, "vision-image-optimizer")


def log_dir():
    """Where the debug log lives (next to the config)."""
    return os.path.join(config_dir(), "logs")


class Settings:
    """One settings store, QSettings-backed or JSON-backed.

    Pass a QSettings object (tests do this to isolate state) or a
    JSON file path to force the fallback backend.
    """

    def __init__(self, backend=None):
        self._qsettings = None
        self._json_path = None
        self._json_data = {}
        if backend is not None and _HAVE_QT and isinstance(
                backend, QSettings):
            self._qsettings = backend
        elif isinstance(backend, str):
            self._json_path = backend
            self._load_json()
        elif _HAVE_QT:
            self._qsettings = QSettings(ORG_NAME, APP_NAME)
        else:
            self._json_path = os.path.join(config_dir(),
                                           "settings.json")
            self._load_json()

    def _load_json(self):
        try:
            with open(self._json_path, encoding="utf-8") as fh:
                self._json_data = json.load(fh)
        except (OSError, ValueError):
            self._json_data = {}

    def _save_json(self):
        os.makedirs(os.path.dirname(self._json_path), exist_ok=True)
        with open(self._json_path, "w", encoding="utf-8") as fh:
            json.dump(self._json_data, fh, indent=2, sort_keys=True)

    def get(self, key, default=None):
        if default is None:
            default = DEFAULTS.get(key)
        if self._qsettings is not None:
            value = self._qsettings.value(key, None)
            if value is None:
                return default
            if isinstance(default, bool):
                if isinstance(value, bool):
                    return value
                return str(value).lower() in ("true", "1", "yes")
            if isinstance(default, int):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default
            return value
        return self._json_data.get(key, default)

    def set(self, key, value):
        if self._qsettings is not None:
            self._qsettings.setValue(key, value)
            self._qsettings.sync()
        else:
            self._json_data[key] = value
            self._save_json()

    def all_values(self):
        """Every setting as a plain dict (for the debug report)."""
        return {key: self.get(key) for key in DEFAULTS}

    # -- typed helpers ------------------------------------------------
    def target_width(self):
        """The resize width the current preset means, or None."""
        preset = self.get("size_preset")
        if preset == "Original":
            return None
        if preset == "Custom":
            return int(self.get("custom_width"))
        return int(preset.rstrip("w"))

    def quality(self):
        preset = self.get("quality_preset")
        if preset == "Custom":
            return int(self.get("custom_quality"))
        return int(preset)

    def optimize_settings(self):
        """The core.optimize_* settings dict from the stored values."""
        return {
            "width": self.target_width(),
            "quality": self.quality(),
            "format": self.get("output_format"),
            "crop": None,
        }

    # -- window geometry (U5) -----------------------------------------
    def get_geometry(self):
        """Saved window geometry bytes, or None when never saved."""
        if self._qsettings is not None:
            from PySide6.QtCore import QByteArray
            value = self._qsettings.value("window_geometry", None)
            if value is None:
                return None
            if isinstance(value, QByteArray):
                return bytes(value)
            return None
        import base64
        encoded = self._json_data.get("window_geometry")
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded)
        except ValueError:
            return None

    def set_geometry(self, data):
        """Save window geometry bytes."""
        if self._qsettings is not None:
            from PySide6.QtCore import QByteArray
            self._qsettings.setValue("window_geometry",
                                     QByteArray(data))
            self._qsettings.sync()
        else:
            import base64
            self._json_data["window_geometry"] = base64.b64encode(
                data).decode("ascii")
            self._save_json()
