"""Key from FFT chroma + Krumhansl-Schmuckler correlation.

The locked algorithm (DESIGN.md, proven by the T31 probes): per
hop frame (window 4096, hop 2048, Hann window), rFFT, keep bins
from 55 Hz to 2 kHz, map each bin to a pitch class, accumulate
log1p(magnitude * 100) per pitch class. Normalize the 12-bin
histogram and correlate (Pearson) with the Krumhansl-Schmuckler
major/minor profiles rotated over all 12 roots (24 candidates).

A top score below 0.5 means key unknown (no usable pitch content,
e.g. a click track or drums-only audio). Otherwise the margin is
the top score minus the second score: margin >= 0.1 is
confident, below that is low and the runner-up key is reported.

Do NOT use YIN pitch for key (monophonic; confidently wrong on
chord stacks) and do NOT blend in a bass histogram (the probes
showed it made every fixture worse).
"""

import numpy as np

SAMPLE_RATE = 44100
WIN_SIZE = 4096
HOP_SIZE = 2048
FREQ_LOW = 55.0
FREQ_HIGH = 2000.0
SCORE_GATE = 0.5
MARGIN_CONFIDENT = 0.1
MIN_FRAMES = 5

# Krumhansl-Schmuckler key profiles (C major / C minor, pitch
# classes C..B). Published constants; do not tune them.
KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52,
            5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54,
            4.75, 3.98, 2.69, 3.34, 3.17]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
              "F#", "G", "G#", "A", "A#", "B"]


def chroma_histogram(samples, sample_rate=SAMPLE_RATE):
    """The 12-bin normalized pitch-class histogram.

    Returns (histogram, frames): the histogram sums to 1, or is
    all zeros when there was too little audio to measure.
    """
    window = np.hanning(WIN_SIZE)
    freqs = np.fft.rfftfreq(WIN_SIZE, 1.0 / sample_rate)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69 + 12 * np.log2(np.maximum(freqs, 1e-9) / 440.0)
    valid = (freqs >= FREQ_LOW) & (freqs <= FREQ_HIGH)
    pcs = np.mod(np.round(midi[valid]).astype(int), 12)
    hist = np.zeros(12)
    frames = 0
    samples = np.asarray(samples, dtype=np.float64)
    for start in range(0, len(samples) - WIN_SIZE + 1, HOP_SIZE):
        frame = samples[start:start + WIN_SIZE] * window
        mag = np.abs(np.fft.rfft(frame))[valid]
        np.add.at(hist, pcs, np.log1p(mag * 100))
        frames += 1
    if frames < MIN_FRAMES or hist.sum() == 0:
        return np.zeros(12), frames
    return hist / hist.sum(), frames


def key_scores(hist):
    """All 24 (score, name, mode) candidates, best first."""
    scores = []
    for root in range(12):
        for profile, mode in ((KS_MAJOR, "major"),
                              (KS_MINOR, "minor")):
            rotated = np.roll(profile, root)
            score = float(np.corrcoef(hist, rotated)[0, 1])
            scores.append((score, NOTE_NAMES[root], mode))
    scores.sort(reverse=True)
    return scores


def measure_key(samples, sample_rate=SAMPLE_RATE):
    """Measure the key from mono float PCM at sample_rate.

    Returns a dict: key ("A minor" or None), confidence
    ("high", "low", or "unknown"), score (top correlation),
    margin (top minus second), runner_up (second key name or
    None), frames (chroma frames analyzed).
    """
    hist, frames = chroma_histogram(samples, sample_rate)
    result = {
        "key": None,
        "confidence": "unknown",
        "score": 0.0,
        "margin": 0.0,
        "runner_up": None,
        "frames": frames,
    }
    if frames < MIN_FRAMES or hist.sum() == 0:
        return result
    scores = key_scores(hist)
    top, second = scores[0], scores[1]
    result["score"] = top[0]
    result["margin"] = top[0] - second[0]
    if top[0] < SCORE_GATE:
        return result
    result["key"] = "%s %s" % (top[1], top[2])
    result["runner_up"] = "%s %s" % (second[1], second[2])
    if result["margin"] >= MARGIN_CONFIDENT:
        result["confidence"] = "high"
    else:
        result["confidence"] = "low"
    return result
