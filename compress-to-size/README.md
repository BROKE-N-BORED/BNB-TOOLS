# T15 — compress-to-size

CLI: `compress-to-size <file> <target-MB>`. Shrink a video to fit under a
size cap. Standalone.

## The math

Sizes in decimal MB (1 MB = 1,000,000 bytes — the way upload limits are
usually stated). For a 100 MB cap it aims at **~88 MB** (margin factor
0.88), because container overhead and bitrate variance mean a file aimed
at exactly the cap lands over it.

```
aim_bytes  = target_MB * 1,000,000 * 0.88
total_kbps = aim_bytes * 8 / duration_s / 1000
video_kbps = total_kbps - audio_kbps      (audio: 128 kbps AAC by default)
```

Worked example (verified by hand in the smoke test): a 3,720s (62 min)
video, 100 MB cap → aim 88,000,000 bytes → total 189.2 kbps → video
61.2 kbps after 128 kbps audio. Short clips get far healthier bitrates: a
60s clip at 100 MB → 11,733 kbps total, ~11,605 kbps video.

Duration comes from `ffprobe` when available, else `--duration` seconds.

## Usage

```bash
python3 compress_to_size.py clip.mp4 100              # print only
python3 compress_to_size.py clip.mp4 100 --run        # encode it
python3 compress_to_size.py clip.mp4 100 --duration 3720
python3 compress_to_size.py clip.mp4 100 --audio-only --run   # audio track only
python3 compress_to_size.py clip.mp4 100 --margin 0.90 --audio-kbps 96
```

Default is **print-only**: it shows the math and the exact ffmpeg command.
`--run` executes it and verifies the result is under the cap. Output is
`<name>-100MB.mp4` (or `<name>-audio-only.m4a`), never overwriting an
existing file. `--no-audio` drops the audio track entirely.

## Requirements

Python 3 stdlib. ffmpeg + ffprobe for probing/encoding (`sudo apt install
ffmpeg`); the math + command printing work without them if `--duration` is
given.
