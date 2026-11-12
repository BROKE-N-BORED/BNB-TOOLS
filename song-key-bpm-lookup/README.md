# T17 — song-key-bpm-lookup

Song key/BPM lookup + mashup-compatibility math. Pairs with BNB SKILLS
**S41**. **TENTATIVE** — the math is fully built; the data source is the
open gap, carried honestly (see below).

## The math (fully built)

- **Key families** incl. relative major/minor, on the Camelot wheel
  (1A–12A minor, 1B–12B major; relatives share a number, e.g. 10A B minor
  / 10B D major)
- **BPM anchor** — tries every song's BPM as the anchor and picks the one
  minimizing total relative stretch
- **Semitone shift** — minimal signed shift (−6…+6) to bring an outlier
  into the anchor key (via the relative key when that is closer)
- **Flags** — a shift of ±5 semitones or more (a tritone+) or a BPM
  stretch over 15% is flagged as "better as its own section / key change";
  ±3–4 semitones is "large but workable"

## Data sources — the honest gap

**Primary: a local JSON file you fill in.** The tool reads key/BPM from
it and does the math. No invented data, no scraped data presented as fact.

```json
{"songs": [{"title": "Tomorrow", "artist": "Silverchair",
            "key": "B minor", "bpm": 146}]}
```

**Optional online provider: MusicBrainz + AcousticBrainz** (free, no API
key, verified live 2026-11-12). MusicBrainz resolves title+artist to a
recording MBID (1 req/sec, User-Agent required); AcousticBrainz supplies
key (high-level) and BPM (low-level). Docs: <https://musicbrainz.org/doc/MusicBrainz_API>
and <https://acousticbrainz.org/data>.

The catch is **coverage**: AcousticBrainz only has data for tracks users
submitted. "Plush" by Stone Temple Pilots resolves on MusicBrainz but has
no AcousticBrainz submission — the tool reports that plainly ("no data"),
never fakes a key. A broad-coverage scriptable key/BPM source is still
needed; the paid APIs (e.g. GetSongBPM) require keys/accounts, which this
tool does not collect.

## Usage

```bash
python3 mashup.py check songs.json
python3 mashup.py check songs.json --json
python3 mashup.py check songs.json --fill-online   # fill missing key/BPM online
python3 mashup.py lookup "Plush" --artist "Stone Temple Pilots"
```

The audit's worked example is in `examples/audit-example.json`
(**illustrative values** reproducing the audit example — 146 BPM anchor,
Plush +4 semitones to B minor — not verified song data):

```bash
python3 mashup.py check examples/audit-example.json
```

## Requirements

Python 3 stdlib only. Network only for `--fill-online` / `lookup`.
