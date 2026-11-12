# T14 — video-capture-ffmpeg-pipeline

Drive the real app, capture it, cut to the 15s sellable-ads structure,
loudness-normalize, fresh filenames per cut. Pairs with BNB SKILLS **S26**
(real-capture promo video production + sellable-ads playbook).

Two scripts:

## `capture.py` — the capture half

Builds the ffmpeg `x11grab` command that records the real product in action
and prints the pre-capture checklist. Default is `--dry-run`: print the
exact command, record nothing.

```bash
python3 capture.py --dry-run
python3 capture.py --dry-run --display :0 --size 1920x1080 --framerate 30
python3 capture.py --run --output raw-capture.mp4 --duration 60
python3 capture.py --checklist
```

Standing rules baked into the checklist: real product only (no stills, no
generated video, no fake UI), no people/hands, sound from real licensed
recordings with CC BY credit lines (never synthesized audio, never his music
unless he named the track for that use).

Needs: an X display + ffmpeg. `capture.py --check` reports availability.

## `cut_video.py` — the cutter/normalizer (fully working)

Cuts raw footage to the 15s structure with chapter markers, two-pass
loudnorm to **-14 LUFS**, fresh timestamped filenames that never overwrite:

| Section | Time | Content |
|---|---|---|
| hook | 0–2s | the result in frame 1 |
| proof | 2–10s | 2–3 real UI beats |
| trust | 10–12s | only if verifiable |
| CTA | 12–15s | "Free download — link in bio" |

```bash
python3 cut_video.py edit-list.json            # writes <name>-YYYYMMDD-HHMMSS.mp4
python3 cut_video.py edit-list.json --dry-run  # print the ffmpeg commands
```

Edit-list format (see `examples/edit-list.json`):

```json
{
  "source": "raw-capture.mp4",
  "name": "code-forge-ad",
  "cuts": [
    {"section": "hook",  "start": 12.5, "end": 14.5},
    {"section": "proof", "start": 30.0, "end": 38.0},
    {"section": "trust", "start": 55.0, "end": 57.0},
    {"section": "cta",   "start": 70.0, "end": 73.0}
  ]
}
```

Cut durations should total 15.0s; the tool warns (does not fail) if they
don't, and reports the actual total. Chapters are embedded as ffmpeg
metadata (`hook` / `proof` / `trust` / `cta`).

## Requirements

ffmpeg + ffprobe on PATH (`sudo apt install ffmpeg`).
Python 3 stdlib only.
