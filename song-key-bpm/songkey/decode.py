"""Decode audio files to float32 mono PCM at 44100 Hz.

miniaudio does the decoding (WAV, MP3, FLAC, OGG) with no system
dependencies. When miniaudio is missing, plain WAV files still
decode through the stdlib wave module. Files recorded at a rate
other than 44100 Hz are resampled with a linear numpy resample.

A file that cannot be read raises DecodeError with a plain message
naming the file, never a traceback.
"""

import array
import os
import wave

import numpy as np

SAMPLE_RATE = 44100
SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".oga")

try:
    import miniaudio
except ImportError:  # miniaudio not installed: wave fallback only
    miniaudio = None


class DecodeError(Exception):
    """A file that cannot be decoded, in plain language."""


def resample_linear(samples, from_rate, to_rate=SAMPLE_RATE):
    """Linear resample of a mono float array to a new sample rate."""
    samples = np.asarray(samples, dtype=np.float64)
    if from_rate == to_rate or len(samples) == 0:
        return samples.astype(np.float32)
    duration = len(samples) / float(from_rate)
    count = int(round(duration * to_rate))
    if count <= 0:
        return np.zeros(0, dtype=np.float32)
    old_x = np.arange(len(samples), dtype=np.float64)
    new_x = np.linspace(0, len(samples) - 1, count)
    return np.interp(new_x, old_x, samples).astype(np.float32)


def _int16_to_float32(raw):
    """Signed 16-bit samples (array or bytes) to float32 in [-1, 1]."""
    if isinstance(raw, array.array):
        data = np.frombuffer(raw.tobytes(), dtype=np.int16)
    else:
        data = np.frombuffer(raw, dtype=np.int16)
    return (data.astype(np.float32) / 32768.0)


def _decode_with_miniaudio(path):
    """Decode with miniaudio at the file's native rate.

    Returns (samples, native_rate). Raises DecodeError on failure.
    """
    try:
        info = miniaudio.get_file_info(path)
        native_rate = info.sample_rate
    except Exception:
        native_rate = SAMPLE_RATE
    try:
        decoded = miniaudio.decode_file(
            path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=native_rate,
        )
    except Exception as exc:
        raise DecodeError(
            "Could not decode %s: %s" % (path, exc))
    samples = _int16_to_float32(decoded.samples)
    return samples, decoded.sample_rate


def _decode_with_wave(path):
    """Decode a plain WAV with the stdlib wave module.

    Returns (samples, native_rate). Raises DecodeError on failure.
    Handles 8, 16, 24, and 32-bit PCM, mono or stereo.
    """
    try:
        with wave.open(path, "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.getnframes()
            raw = wf.readframes(frames)
    except (wave.Error, EOFError, OSError) as exc:
        raise DecodeError(
            "Could not decode %s: not a readable WAV file (%s)"
            % (path, exc))
    if frames == 0:
        raise DecodeError(
            "Could not decode %s: the file has no audio in it" % path)
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
                - 128.0) / 128.0
    elif width == 2:
        data = _int16_to_float32(raw)
    elif width == 3:
        triplets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (triplets[:, 0].astype(np.int32)
                | (triplets[:, 1].astype(np.int32) << 8)
                | (triplets[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / float(1 << 23)
    elif width == 4:
        data = (np.frombuffer(raw, dtype=np.int32).astype(np.float32)
                / 2147483648.0)
    else:
        raise DecodeError(
            "Could not decode %s: %d-bit WAV is not supported"
            % (path, width * 8))
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32), rate


def decode_audio(path):
    """Decode one audio file.

    Returns (samples, duration): samples is float32 mono PCM at
    44100 Hz, duration is seconds as a float. Raises DecodeError
    with a plain message naming the file when it cannot be read.
    """
    if not os.path.exists(path):
        raise DecodeError(
            "Could not find %s: no such file" % path)
    if not os.path.isfile(path):
        raise DecodeError(
            "Could not read %s: it is not a file" % path)
    last_error = None
    if miniaudio is not None:
        try:
            samples, native_rate = _decode_with_miniaudio(path)
        except DecodeError as exc:
            last_error = exc
        else:
            return _finish(samples, native_rate)
    # miniaudio missing or failed: try the stdlib WAV fallback.
    if os.path.splitext(path)[1].lower() == ".wav":
        try:
            samples, native_rate = _decode_with_wave(path)
        except DecodeError as exc:
            last_error = exc
        else:
            return _finish(samples, native_rate)
    if last_error is not None:
        raise last_error
    raise DecodeError(
        "Could not decode %s: this file type needs miniaudio, "
        "which is not installed" % path)


def _finish(samples, native_rate):
    """Resample to 44100 Hz when needed; return (samples, seconds)."""
    if native_rate != SAMPLE_RATE:
        samples = resample_linear(samples, native_rate, SAMPLE_RATE)
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    duration = len(samples) / float(SAMPLE_RATE)
    return samples, duration
