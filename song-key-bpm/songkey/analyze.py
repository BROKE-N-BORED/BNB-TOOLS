"""analyze_file: decode one file and measure its BPM and key.

Returns the result dict from the DESIGN.md JSON schema, with
these keys exactly: path, file, bpm, bpm_confidence, tempo_bpm,
key, key_confidence, key_score, key_margin, key_runner_up,
duration, error. A file that cannot be decoded still returns a
result, with error set to a plain message and the measurements
left null; it never raises and never embeds a traceback.
"""

import os

from .decode import DecodeError, decode_audio
from .key import measure_key
from .tempo import measure_tempo

RESULT_KEYS = (
    "path", "file", "bpm", "bpm_confidence", "tempo_bpm",
    "key", "key_confidence", "key_score", "key_margin",
    "key_runner_up", "duration", "error",
)


def _round(value, places):
    if value is None:
        return None
    return round(float(value), places)


def analyze_file(path):
    """Analyze one audio file; return the result dict."""
    result = {
        "path": os.path.abspath(path),
        "file": os.path.basename(path),
        "bpm": None,
        "bpm_confidence": "unknown",
        "tempo_bpm": None,
        "key": None,
        "key_confidence": "unknown",
        "key_score": None,
        "key_margin": None,
        "key_runner_up": None,
        "duration": None,
        "error": None,
    }
    try:
        samples, duration = decode_audio(path)
    except DecodeError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # a decode crash is a plain error too
        result["error"] = ("Could not decode %s: %s"
                           % (path, exc))
        return result
    result["duration"] = _round(duration, 3)
    tempo = measure_tempo(samples)
    result["bpm"] = _round(tempo["bpm"], 1)
    result["bpm_confidence"] = tempo["confidence"]
    result["tempo_bpm"] = _round(tempo["tempo_bpm"], 1)
    key = measure_key(samples)
    result["key"] = key["key"]
    result["key_confidence"] = key["confidence"]
    result["key_score"] = _round(key["score"], 3)
    result["key_margin"] = _round(key["margin"], 3)
    result["key_runner_up"] = key["runner_up"]
    return result
