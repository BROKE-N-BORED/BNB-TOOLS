#!/usr/bin/env python3
"""Smoke test for T17 song-key-bpm-lookup.

1. --help
2. Unit checks of the key math (Camelot map, relatives, semitone shifts)
3. The audit's worked example (Tomorrow / Alive / Plush): must reproduce
   the 146 BPM anchor and Plush +4 semitones to B minor
4. Offline parse check of the AcousticBrainz response shape
5. Best-effort live online probe (reports honestly; a rate-limit or
   no-data answer is not a failure — only a crash is)
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "mashup.py"
sys.path.insert(0, str(HERE.parent))
import mashup  # noqa: E402
import lookup_online  # noqa: E402


def run(*args, timeout=120):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    # Key math unit checks.
    K = mashup.Key.parse
    checks = [
        (K("B minor").camelot_label, "10A"),
        (K("D major").camelot_label, "10B"),
        (K("G minor").camelot_label, "6A"),
        (K("A minor").camelot_label, "8A"),
        (K("C major").camelot_label, "8B"),
        (str(K("B minor").relative), "D major"),
        (str(K("D major").relative), "B minor"),
        (str(K("G minor").relative), "Bb major"),
        (mashup.semitone_shift(K("G minor"), K("B minor")), 4),
        (mashup.semitone_shift(K("B minor"), K("G minor")), -4),
        (mashup.semitone_shift(K("C major"), K("F# major")), 6),
        (mashup.key_relation(K("B minor"), K("D major"))[0],
         "relative major/minor (same Camelot number)"),
    ]
    for got, want in checks:
        print("== key check: got %r want %r %s"
              % (got, want, "OK" if got == want else "MISMATCH"))
        if got != want:
            fails.append("key math: got %r, want %r" % (got, want))

    # The audit's worked example.
    p = run("check", str(HERE.parent / "examples" / "audit-example.json"),
            "--json")
    print("== audit example exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0:
        fails.append("audit example run failed: %s" % p.stderr)
    else:
        out = json.loads(p.stdout)
        if out["anchor_bpm"] != 146:
            fails.append("anchor BPM should be 146, got %r"
                         % out["anchor_bpm"])
        if out["anchor_key"] != "B minor":
            fails.append("anchor key should be B minor, got %r"
                         % out["anchor_key"])
        by_title = {s["title"]: s for s in out["songs"]}
        plush = by_title["Plush"]
        if plush.get("shift_semitones") != 4:
            fails.append("Plush shift should be +4, got %r"
                         % plush.get("shift_semitones"))
        if plush.get("shift_to") != "B minor":
            fails.append("Plush shift target should be B minor, got %r"
                         % plush.get("shift_to"))
        alive = by_title["Alive"]
        if alive.get("shift_semitones") != 0:
            fails.append("Alive (D major, relative of B minor) should "
                         "need no shift, got %r"
                         % alive.get("shift_semitones"))
        if out["anchor_key_family"] != ["Tomorrow", "Alive"]:
            fails.append("key family should be Tomorrow + Alive, got %r"
                         % out["anchor_key_family"])

    # Flag check: a distant key (+6 semitones) must be flagged own-section.
    far = [{"title": "A", "artist": "", "key": "C major", "bpm": 120},
           {"title": "B", "artist": "", "key": "C major", "bpm": 120},
           {"title": "C", "artist": "", "key": "F# major", "bpm": 120}]
    out = mashup.analyze(far)
    c = [s for s in out["songs"] if s["title"] == "C"][0]
    print("== distant-key flag: %s" % c.get("flag"))
    if not c.get("flag") or "own section" not in c["flag"]:
        fails.append("a +6 semitone outlier should be flagged own-section")

    # AcousticBrainz parse check (offline, canned response shape).
    parsed = lookup_online.parse_acousticbrainz(
        {"tonal": {"key_key": "B", "key_scale": "minor",
                   "key_strength": 0.83}},
        {"rhythm": {"bpm": 145.7}})
    print("== AB parse: %r" % parsed)
    if parsed != {"key": "B minor", "key_strength": 0.83, "bpm": 146}:
        fails.append("AcousticBrainz parse wrong: %r" % parsed)

    # Best-effort live probe — honest reporting only.
    try:
        res = lookup_online.lookup_song("Plush", "Stone Temple Pilots")
        print("== live online probe: %s"
              % json.dumps(res, indent=2))
        if res.get("mbid"):
            print("   (MusicBrainz resolved the recording; "
                  "AcousticBrainz data: %s)"
                  % ("present" if res.get("key") or res.get("bpm")
                     else "absent — sparse coverage, as documented"))
    except Exception as e:
        fails.append("live probe crashed: %s" % e)

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
