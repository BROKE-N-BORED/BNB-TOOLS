#!/usr/bin/env python3
"""T17 — song-key-bpm-lookup (pairs with BNB SKILLS S41). TENTATIVE.

Mashup-compatibility math, fully built:
  * key families incl. relative major/minor (Camelot-style wheel)
  * BPM anchor selection with minimal total stretch
  * semitone shift to bring an outlier into key
  * flag as own-section / key-change when the shift (or the BPM stretch)
    is too big

Data lookup is a SCAFFOLD with two providers:
  * JSON file (primary): a local data file the user fills in. The tool
    reads key/BPM from it and does the math. No invented data.
  * Online (optional, --fill-online / lookup): MusicBrainz search
    (no key, 1 req/sec) to resolve title+artist to a recording MBID,
    then AcousticBrainz for key (high-level) and BPM (low-level).
    Free, no API key. Coverage is SPARSE — AcousticBrainz only has data
    for tracks users submitted, so most lookups return "no data". That
    is reported honestly, never papered over.

A scriptable key/BPM data source with broad coverage is still an open gap:
the paid APIs (GetSongBPM etc.) need keys/accounts, and the free ones are
sparse. Do not present scraped or invented key/BPM data as fact.

Usage:
    mashup.py check songs.json
    mashup.py check songs.json --json
    mashup.py lookup "Plush" --artist "Stone Temple Pilots"
    mashup.py check songs.json --fill-online

songs.json format:
    {"songs": [{"title": "Tomorrow", "artist": "Silverchair",
                "key": "B minor", "bpm": 146}, ...]}
    key may be null and bpm may be null; --fill-online tries to fill them.

Exit 0 = check completed, 1 = bad input / lookup failure.
"""
import argparse
import json
import os
import sys

# ---------------------------------------------------------------- key math
# Display spellings follow conventional key signatures (Db/Eb/Ab/Bb flat,
# F# sharp) so the relative of G minor prints "Bb major", not "A# major".
NOTES_DISPLAY = ["C", "Db", "D", "Eb", "E", "F",
                 "F#", "G", "Ab", "A", "Bb", "B"]
NOTE_VALUES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
               "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
               "A#": 10, "BB": 10, "B": 11}

# Camelot wheel, standard numbering. Minor keys are "A", major "B".
# Relative major/minor share a number (10A B minor / 10B D major).
CAMELOT_MINOR = {  # tonic value -> Camelot number
    8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7, 9: 8, 4: 9, 11: 10,
    6: 11, 1: 12,
}
CAMELOT_MAJOR = {  # tonic value -> Camelot number
    11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7, 0: 8, 7: 9, 2: 10,
    9: 11, 4: 12,
}
CAMELOT_NAME = {  # (number, letter) -> display name
    (1, "A"): "Ab minor", (2, "A"): "Eb minor", (3, "A"): "Bb minor",
    (4, "A"): "F minor", (5, "A"): "C minor", (6, "A"): "G minor",
    (7, "A"): "D minor", (8, "A"): "A minor", (9, "A"): "E minor",
    (10, "A"): "B minor", (11, "A"): "F# minor", (12, "A"): "Db minor",
    (1, "B"): "B major", (2, "B"): "F# major", (3, "B"): "Db major",
    (4, "B"): "Ab major", (5, "B"): "Eb major", (6, "B"): "Bb major",
    (7, "B"): "F major", (8, "B"): "C major", (9, "B"): "G major",
    (10, "B"): "D major", (11, "B"): "A major", (12, "B"): "E major",
}


class Key:
    def __init__(self, tonic, mode):
        self.tonic = tonic % 12
        self.mode = mode  # "major" or "minor"

    @classmethod
    def parse(cls, text):
        """Parse 'B minor', 'Bm', 'D major', 'F#m', 'Eb major', 'G'."""
        if text is None:
            return None
        t = text.strip()
        low = t.lower()
        if low.endswith("minor"):
            mode, note = "minor", low[:-5].strip()
        elif low.endswith("major"):
            mode, note = "major", low[:-5].strip()
        elif low.endswith("min"):
            mode, note = "minor", low[:-3].strip()
        elif low.endswith("maj"):
            mode, note = "major", low[:-3].strip()
        elif low.endswith("m") and len(low) > 1:
            mode, note = "minor", low[:-1].strip()
        else:
            mode, note = "major", low
        note = note.upper().replace("♯", "#").replace("♭", "B")
        if note not in NOTE_VALUES:
            raise ValueError("unrecognized key %r" % text)
        return cls(NOTE_VALUES[note], mode)

    @property
    def camelot(self):
        if self.mode == "minor":
            return (CAMELOT_MINOR[self.tonic], "A")
        return (CAMELOT_MAJOR[self.tonic], "B")

    @property
    def camelot_label(self):
        n, letter = self.camelot
        return "%d%s" % (n, letter)

    @property
    def relative(self):
        """Relative major (for a minor key) or relative minor (major)."""
        if self.mode == "minor":
            return Key(self.tonic + 3, "major")
        return Key(self.tonic - 3, "minor")

    def shifted(self, semitones):
        return Key(self.tonic + semitones, self.mode)

    def __str__(self):
        return "%s %s" % (NOTES_DISPLAY[self.tonic], self.mode)

    def __eq__(self, other):
        return (isinstance(other, Key) and self.tonic == other.tonic
                and self.mode == other.mode)

    def __hash__(self):
        return hash((self.tonic, self.mode))


def semitone_shift(from_key, to_key):
    """Minimal signed semitone shift (-6..+6) from one tonic to another
    (same mode assumed; caller handles mode via the relative key)."""
    d = (to_key.tonic - from_key.tonic) % 12
    return d - 12 if d > 6 else d


def key_relation(a, b):
    """How two keys relate for mixing. Returns (label, compatible)."""
    if a == b:
        return "same key", True
    if a.relative == b or b.relative == a:
        return "relative major/minor (same Camelot number)", True
    na, la = a.camelot
    nb, lb = b.camelot
    if la == lb and abs(na - nb) in (1, 11):
        return ("adjacent on the wheel (%s -> %s)"
                % (a.camelot_label, b.camelot_label)), True
    return "distant (%s vs %s)" % (a.camelot_label, b.camelot_label), False


# ---------------------------------------------------------------- mashup math
def pick_bpm_anchor(songs):
    """Pick the BPM (one of the songs') minimizing total relative stretch.

    Returns (anchor_bpm, {title: stretch_fraction}, total_stretch).
    """
    bpms = [s["bpm"] for s in songs if s.get("bpm")]
    if not bpms:
        return None, {}, None
    best = None
    for anchor in bpms:
        total = sum(abs(b - anchor) / b for b in bpms)
        if best is None or total < best[1]:
            best = (anchor, total)
    anchor, total = best
    stretches = {s["title"]: (anchor - s["bpm"]) / s["bpm"]
                 for s in songs if s.get("bpm")}
    return anchor, stretches, total


def pick_anchor_key(songs):
    """The key family (Camelot number, either letter) shared by the most
    songs. Returns (Key to shift outliers toward, member titles)."""
    families = {}
    for s in songs:
        k = s.get("_key")
        if k is None:
            continue
        families.setdefault(k.camelot[0], []).append(s)
    if not families:
        return None, []
    best_num = max(families, key=lambda n: len(families[n]))
    members = families[best_num]
    # Anchor key: the minor key of the family if any member is minor,
    # else the major key (mashups usually anchor on the minor).
    minor = [s for s in members if s["_key"].mode == "minor"]
    anchor_song = minor[0] if minor else members[0]
    return anchor_song["_key"], [s["title"] for s in members]


def analyze(songs):
    """Full compatibility analysis. Songs carry _key (Key or None)."""
    for s in songs:
        s["_key"] = Key.parse(s["key"]) if s.get("key") else None
    anchor_key, family = pick_anchor_key(songs)
    anchor_bpm, stretches, _total = pick_bpm_anchor(songs)
    out = {"anchor_key": str(anchor_key) if anchor_key else None,
           "anchor_key_camelot": (anchor_key.camelot_label
                                  if anchor_key else None),
           "anchor_key_family": family,
           "anchor_bpm": anchor_bpm,
           "songs": [], "verdict": None}
    problems = []
    for s in songs:
        rec = {"title": s["title"], "artist": s.get("artist", ""),
               "key": s.get("key"), "bpm": s.get("bpm"),
               "camelot": s["_key"].camelot_label if s["_key"] else None}
        if s["_key"] and anchor_key:
            rel, compat = key_relation(s["_key"], anchor_key)
            rec["key_relation"] = rel
            rec["in_key_family"] = s["_key"].camelot[0] == anchor_key.camelot[0]
            if s["_key"] == anchor_key or s["_key"].relative == anchor_key \
                    or anchor_key.relative == s["_key"]:
                rec["shift_semitones"] = 0
                rec["shift_to"] = None
            else:
                # Shift toward the anchor key's mode via the relative key
                # when that is closer.
                target = anchor_key
                if s["_key"].mode != anchor_key.mode:
                    target = anchor_key.relative
                shift = semitone_shift(s["_key"], target)
                rec["shift_semitones"] = shift
                rec["shift_to"] = str(target)
                if abs(shift) >= 5:
                    rec["flag"] = ("shift of %+d semitones is a tritone or "
                                   "more — better as its own section / "
                                   "key change" % shift)
                    problems.append(rec["flag"])
                elif abs(shift) >= 3:
                    rec["flag"] = ("shift of %+d semitones is large but "
                                   "workable — pitch shift will be audible"
                                   % shift)
        if s.get("bpm") and anchor_bpm:
            stretch = stretches[s["title"]]
            rec["bpm_stretch_pct"] = round(stretch * 100, 1)
            if abs(stretch) > 0.15:
                rec["flag"] = ((rec.get("flag", "") + " ") +
                               "BPM stretch %.1f%% is large — consider "
                               "its own section" % (stretch * 100))
                problems.append("BPM stretch for %s" % s["title"])
        out["songs"].append(rec)
    if anchor_key and anchor_bpm:
        out["verdict"] = ("mashup anchor: %s (%s) at %d BPM"
                          % (anchor_key, anchor_key.camelot_label,
                             anchor_bpm))
    return out


# ---------------------------------------------------------------- CLI
def load_songs(path):
    with open(path) as f:
        data = json.load(f)
    songs = data["songs"]
    for s in songs:
        if "title" not in s:
            raise ValueError("each song needs a 'title'")
    return songs


def print_report(out):
    print("MASHUP COMPATIBILITY")
    print("-" * 60)
    print("%-28s %-12s %-6s %s" % ("song", "key", "bpm", "camelot"))
    for s in out["songs"]:
        print("%-28s %-12s %-6s %s"
              % (s["title"][:28], s.get("key") or "?",
                 s.get("bpm") or "?", s.get("camelot") or "?"))
    print("-" * 60)
    if out["verdict"]:
        print(out["verdict"])
    print("key family: %s" % ", ".join(out["anchor_key_family"]))
    for s in out["songs"]:
        bits = []
        if s.get("key_relation"):
            bits.append(s["key_relation"])
        if s.get("shift_semitones"):
            bits.append("shift %+d semitones to %s"
                        % (s["shift_semitones"], s["shift_to"]))
        if s.get("bpm_stretch_pct") is not None:
            bits.append("BPM stretch %+.1f%%" % s["bpm_stretch_pct"])
        if bits:
            print("  %s: %s" % (s["title"], "; ".join(bits)))
        if s.get("flag"):
            print("  !! %s: %s" % (s["title"], s["flag"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Song key/BPM lookup + mashup compatibility math.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="analyze a songs JSON file")
    p.add_argument("file", help="songs JSON file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fill-online", action="store_true",
                   help="fill missing key/BPM via MusicBrainz + "
                        "AcousticBrainz (free, sparse coverage)")

    p = sub.add_parser("lookup", help="look up one song online")
    p.add_argument("title")
    p.add_argument("--artist", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "lookup":
        from lookup_online import lookup_song
        res = lookup_song(args.title, args.artist)
        print(json.dumps(res, indent=2))
        return 0 if res.get("key") or res.get("bpm") else 1

    try:
        songs = load_songs(args.file)
    except (OSError, ValueError, KeyError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    if args.fill_online:
        from lookup_online import lookup_song
        for s in songs:
            if s.get("key") and s.get("bpm"):
                continue
            res = lookup_song(s["title"], s.get("artist", ""))
            if res.get("key") and not s.get("key"):
                s["key"] = res["key"]
                print("filled key for %s: %s (AcousticBrainz)"
                      % (s["title"], res["key"]))
            if res.get("bpm") and not s.get("bpm"):
                s["bpm"] = res["bpm"]
                print("filled BPM for %s: %s (AcousticBrainz)"
                      % (s["title"], res["bpm"]))
            if not res.get("key") and not res.get("bpm"):
                print("no online data for %s — %s"
                      % (s["title"], res.get("note", "")))
    out = analyze(songs)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print_report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
