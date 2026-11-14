"""Fixture generators for the song-key-bpm tests.

Every fixture is generated on the fly with numpy + stdlib wave;
no binary fixtures live in the tree. The generators are copied
from the T31 probes (probe.py, probe4.py), which proved the
algorithm against these exact signals.

Fixtures:
  click120  click track, exactly 120 BPM
  click147  click track, exactly 147 BPM
  cmajor    C major chord loop (C F G C triads, sine stacks)
  aminor    A minor chord loop (Am Dm E Am triads)
  combo     C major chords + 120 BPM click together
  gmajor    G major chord loop (G C D G triads)
  eminor    E minor chord loop (Em Am B Em triads)
"""

import os
import subprocess
import wave

import numpy as np

SR = 44100

NOTE_FREQ = {
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23,
    "F#4": 369.99, "G4": 392.00, "G#4": 415.30, "A4": 440.00,
    "B4": 493.88, "C5": 523.25, "D5": 587.33, "E5": 659.25,
    "F5": 698.46, "F#5": 739.99, "G5": 783.99, "A5": 880.00,
}

C_MAJOR_CHORDS = [["C4", "E4", "G4"], ["F4", "A4", "C5"],
                  ["G4", "B4", "D5"], ["C4", "E4", "G4"]]
A_MINOR_CHORDS = [["A4", "C5", "E5"], ["D4", "F4", "A4"],
                  ["E4", "G#4", "B4"], ["A4", "C5", "E5"]]
G_MAJOR_CHORDS = [["G4", "B4", "D5"], ["C4", "E4", "G4"],
                  ["D4", "F#4", "A4"], ["G4", "B4", "D5"]]
E_MINOR_CHORDS = [["E4", "G4", "B4"], ["A4", "C5", "E5"],
                  ["B4", "D5", "F#5"], ["E4", "G4", "B4"]]

FIXTURE_NAMES = ("click120", "click147", "cmajor", "aminor",
                 "combo", "gmajor", "eminor")


def write_wav(path, samples, sr=SR):
    """Write mono float samples as a 16-bit WAV at sr."""
    samples = np.asarray(samples, dtype=np.float64)
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.8
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def click_track(bpm, seconds=10, sr=SR):
    """A click track: short decaying 2 kHz blips on the beat."""
    n = int(sr * seconds)
    sig = np.zeros(n)
    period = int(sr * 60.0 / bpm)
    click_len = int(sr * 0.03)
    t = np.arange(click_len) / sr
    click = np.sin(2 * np.pi * 2000 * t) * np.exp(-t * 120)
    for start in range(0, n - click_len, period):
        sig[start:start + click_len] += click
    return sig


def chord_loop(chords, seconds_each=2, click_bpm=None, sr=SR):
    """Sine-stack triads in sequence, with fades at the joins."""
    parts = []
    for chord in chords:
        n = int(sr * seconds_each)
        t = np.arange(n) / sr
        sig = np.zeros(n)
        for note in chord:
            sig += np.sin(2 * np.pi * NOTE_FREQ[note] * t)
        sig /= len(chord)
        fade = int(sr * 0.05)
        sig[:fade] *= np.linspace(0, 1, fade)
        sig[-fade:] *= np.linspace(1, 0, fade)
        parts.append(sig)
    sig = np.concatenate(parts)
    if click_bpm:
        sig = sig + 0.5 * click_track(click_bpm, len(sig) / sr, sr)
    return sig


def fixture_samples(name):
    """The generated samples for one fixture name."""
    if name == "click120":
        return click_track(120)
    if name == "click147":
        return click_track(147)
    if name == "cmajor":
        return chord_loop(C_MAJOR_CHORDS)
    if name == "aminor":
        return chord_loop(A_MINOR_CHORDS)
    if name == "combo":
        return chord_loop(C_MAJOR_CHORDS, click_bpm=120)
    if name == "gmajor":
        return chord_loop(G_MAJOR_CHORDS)
    if name == "eminor":
        return chord_loop(E_MINOR_CHORDS)
    raise ValueError("unknown fixture: %s" % name)


def make_fixture(name, directory, sr=SR):
    """Write one fixture WAV into directory; return its path."""
    path = os.path.join(directory, name + ".wav")
    if sr == SR:
        samples = fixture_samples(name)
    elif name in ("click120", "click147"):
        samples = click_track(int(name[5:]), sr=sr)
    else:
        chords = {"cmajor": C_MAJOR_CHORDS, "aminor": A_MINOR_CHORDS,
                  "gmajor": G_MAJOR_CHORDS, "eminor": E_MINOR_CHORDS,
                  "combo": C_MAJOR_CHORDS}[name]
        samples = chord_loop(
            chords, click_bpm=120 if name == "combo" else None, sr=sr)
    write_wav(path, samples, sr=sr)
    return path


def make_fixture_dir(directory, names=FIXTURE_NAMES):
    """Write several fixtures into directory; return their paths."""
    os.makedirs(directory, exist_ok=True)
    return [make_fixture(name, directory) for name in names]


def make_mp3(wav_path, mp3_path):
    """Encode a WAV as MP3 with ffmpeg (raises if ffmpeg fails)."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
         "-codec:a", "libmp3lame", "-b:a", "192k", mp3_path],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed: %s" % result.stderr.strip())
    return mp3_path
