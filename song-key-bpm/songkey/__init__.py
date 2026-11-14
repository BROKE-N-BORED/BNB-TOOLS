"""Song Key BPM: a local song key and BPM analyzer.

Analyzes audio files on the machine, with no network and no
account: BPM from onset intervals, key from FFT chroma matched
against the Krumhansl-Schmuckler profiles. See DESIGN.md for the
locked algorithm.
"""

__version__ = "0.1.0"
APP_NAME = "Song Key BPM"
APP_SLUG = "song-key-bpm"
