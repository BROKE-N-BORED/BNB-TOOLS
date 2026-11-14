"""BPM from onset intervals, with an aubio.tempo cross-check.

The locked algorithm (DESIGN.md, proven by the T31 probes):
feed decoded PCM straight to aubio.onset, take the median of the
kept onset intervals, fold into 60-180 BPM. Fewer than 10 onsets
or fewer than 8 kept intervals means BPM is unknown (a beatless
file, e.g. chords with no drums). aubio.tempo's get_bpm() over the
same PCM is recorded as the cross-check; when it disagrees with
the onset BPM by more than 5%, confidence drops to low and the
onset value is kept (the tempo tracker hallucinates on beatless
audio).
"""

import numpy as np

import aubio

SAMPLE_RATE = 44100
WIN_SIZE = 1024
HOP_SIZE = 512
MIN_ONSETS = 10
MIN_INTERVALS = 8
INTERVAL_LOW = 0.15
INTERVAL_HIGH = 2.0
BPM_LOW = 60.0
BPM_HIGH = 180.0
CROSS_CHECK_TOLERANCE = 0.05


def _feed_frames(samples, hop=HOP_SIZE):
    """Yield hop-sized float32 frames, zero-padded at the end."""
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    total = len(samples)
    start = 0
    while start < total:
        frame = samples[start:start + hop]
        if len(frame) < hop:
            padded = np.zeros(hop, dtype=np.float32)
            padded[:len(frame)] = frame
            frame = padded
        yield frame
        start += hop


def measure_tempo(samples, sample_rate=SAMPLE_RATE):
    """Measure BPM from mono float PCM at sample_rate.

    Returns a dict: bpm (float or None), confidence
    ("high", "low", or "unknown"), tempo_bpm (the cross-check,
    float or None), onsets (count), intervals (kept count).
    """
    onset = aubio.onset("default", WIN_SIZE, HOP_SIZE, sample_rate)
    times = []
    for frame in _feed_frames(samples):
        if onset(frame):
            times.append(onset.get_last_s())
    tempo = aubio.tempo("default", WIN_SIZE, HOP_SIZE, sample_rate)
    for frame in _feed_frames(samples):
        tempo(frame)
    cross = float(tempo.get_bpm())
    tempo_bpm = cross if cross > 0 else None

    result = {
        "bpm": None,
        "confidence": "unknown",
        "tempo_bpm": tempo_bpm,
        "onsets": len(times),
        "intervals": 0,
    }
    if len(times) < MIN_ONSETS:
        return result
    intervals = np.diff(np.asarray(times, dtype=np.float64))
    kept = intervals[(intervals > INTERVAL_LOW)
                     & (intervals < INTERVAL_HIGH)]
    result["intervals"] = int(len(kept))
    if len(kept) < MIN_INTERVALS:
        return result
    bpm = 60.0 / float(np.median(kept))
    while bpm > BPM_HIGH:
        bpm /= 2
    while bpm < BPM_LOW:
        bpm *= 2
    result["bpm"] = bpm
    result["confidence"] = "high"
    if tempo_bpm is not None and abs(tempo_bpm - bpm) / bpm > \
            CROSS_CHECK_TOLERANCE:
        result["confidence"] = "low"
    return result
