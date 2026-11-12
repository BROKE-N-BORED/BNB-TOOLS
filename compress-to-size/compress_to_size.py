#!/usr/bin/env python3
"""T15 — compress-to-size (standalone).

    compress-to-size <file> <target-MB>

Shrink a video to fit under a size cap. Bitrate math from duration + target
size, with a safety margin: for a 100 MB cap it aims at ~88 MB (margin
factor 0.88), because container overhead and bitrate variance mean a file
aimed at exactly the cap lands over it.

Math (all in decimal MB, 1 MB = 1,000,000 bytes — the way upload limits
are usually stated):
    aim_bytes     = target_MB * 1,000,000 * 0.88
    total_kbps    = aim_bytes * 8 / duration_s / 1000
    video_kbps    = total_kbps - audio_kbps
    audio_kbps    = 128 by default (AAC), 0 with --no-audio

Duration comes from ffprobe when available, else --duration seconds.

Default is print-only: it shows the math and the exact ffmpeg command.
--run executes it. --audio-only extracts the audio track instead (useful
when the audio is what matters and the video can go).

Usage:
    compress_to_size.py clip.mp4 100
    compress_to_size.py clip.mp4 100 --run
    compress_to_size.py clip.mp4 100 --duration 3720
    compress_to_size.py clip.mp4 100 --audio-only --run
    compress_to_size.py clip.mp4 100 --margin 0.90 --audio-kbps 96

Exit 0 = math done (and, with --run, the file was produced and verified
under the cap); 1 = failure.
"""
import argparse
import os
import shutil
import subprocess
import sys

MARGIN = 0.88          # aim at 88% of the cap
DEFAULT_AUDIO_KBPS = 128


def probe_duration(path):
    if not shutil.which("ffprobe"):
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def bitrate_math(duration_s, target_mb, margin=MARGIN,
                 audio_kbps=DEFAULT_AUDIO_KBPS):
    """Return a dict of the bitrate plan. Raises ValueError on bad input."""
    if duration_s <= 0:
        raise ValueError("duration must be > 0")
    if target_mb <= 0:
        raise ValueError("target size must be > 0")
    aim_bytes = target_mb * 1_000_000 * margin
    total_kbps = aim_bytes * 8 / duration_s / 1000.0
    video_kbps = total_kbps - audio_kbps
    if video_kbps < 50:
        raise ValueError(
            "video bitrate would be %.0f kbps (total %.0f - audio %d) — "
            "too low to encode; raise the target size or shorten the video"
            % (video_kbps, total_kbps, audio_kbps))
    return {
        "aim_bytes": aim_bytes,
        "aim_mb": aim_bytes / 1_000_000,
        "total_kbps": total_kbps,
        "audio_kbps": audio_kbps,
        "video_kbps": video_kbps,
    }


def build_command(src, out, plan, audio_only=False):
    if audio_only:
        return ["ffmpeg", "-y", "-v", "error", "-i", src,
                "-vn", "-c:a", "aac", "-b:a",
                "%dk" % plan["audio_kbps"], out]
    return ["ffmpeg", "-y", "-v", "error", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "%dk" % round(plan["video_kbps"]),
            "-maxrate", "%dk" % round(plan["video_kbps"] * 1.2),
            "-bufsize", "%dk" % round(plan["video_kbps"] * 2),
            "-c:a", "aac", "-b:a", "%dk" % plan["audio_kbps"],
            "-movflags", "+faststart", out]


def out_name(src, target_mb, audio_only):
    base, _ext = os.path.splitext(src)
    suffix = "-audio-only" if audio_only else "-%dMB" % target_mb
    out = base + suffix + (".m4a" if audio_only else ".mp4")
    n = 2
    while os.path.exists(out):
        out = "%s%s-%d%s" % (base, suffix, n,
                             ".m4a" if audio_only else ".mp4")
        n += 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compress a video to fit under a size cap (bitrate "
                    "math + ffmpeg command; print-only by default).")
    ap.add_argument("file", help="input video file")
    ap.add_argument("target_mb", type=float,
                    help="size cap in MB (aims at 88%% of it)")
    ap.add_argument("--duration", type=float,
                    help="duration in seconds (else probed with ffprobe)")
    ap.add_argument("--margin", type=float, default=MARGIN,
                    help="safety margin factor (default 0.88)")
    ap.add_argument("--audio-kbps", type=int, default=DEFAULT_AUDIO_KBPS)
    ap.add_argument("--no-audio", action="store_true",
                    help="drop the audio track entirely")
    ap.add_argument("--audio-only", action="store_true",
                    help="extract the audio track instead of the video")
    ap.add_argument("--run", action="store_true",
                    help="execute the ffmpeg command (default: print only)")
    ap.add_argument("--output", help="output filename (default: derived)")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.file):
        print("error: no such file: %s" % args.file, file=sys.stderr)
        return 2
    duration = args.duration
    if duration is None:
        duration = probe_duration(args.file)
        if duration is None:
            print("error: could not probe duration (ffprobe missing or "
                  "failed) — pass --duration SECONDS.", file=sys.stderr)
            return 1
        print("duration: %.1fs (probed with ffprobe)" % duration)
    else:
        print("duration: %.1fs (given with --duration)" % duration)

    audio_kbps = 0 if args.no_audio else args.audio_kbps
    try:
        plan = bitrate_math(duration, args.target_mb,
                            margin=args.margin, audio_kbps=audio_kbps)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1

    print("target cap: %.0f MB -> aiming at %.1f MB (margin %.2f)"
          % (args.target_mb, plan["aim_mb"], args.margin))
    print("total bitrate: %.0f kbps = video %.0f kbps + audio %d kbps"
          % (plan["total_kbps"], plan["video_kbps"], plan["audio_kbps"]))
    out = args.output or out_name(args.file, args.target_mb,
                                  args.audio_only)
    cmd = build_command(args.file, out, plan, args.audio_only)
    print()
    print("ffmpeg command:")
    print("  " + " ".join(cmd))
    if args.audio_only:
        print()
        print("audio-only: video dropped; output is the audio track.")
    if not args.run:
        print()
        print("PRINT ONLY — nothing encoded. Re-run with --run to encode.")
        return 0
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not found on PATH.", file=sys.stderr)
        return 1
    print()
    print("encoding to %s ..." % out)
    p = subprocess.run(cmd)
    if p.returncode != 0:
        print("error: ffmpeg failed (exit %d)" % p.returncode,
              file=sys.stderr)
        return 1
    size_mb = os.path.getsize(out) / 1_000_000
    cap = args.target_mb
    print("done: %s — %.1f MB (cap %.0f MB) — %s"
          % (out, size_mb, cap,
             "UNDER CAP" if size_mb <= cap else "OVER CAP — re-run with "
             "a smaller margin"))
    return 0 if size_mb <= cap else 1


if __name__ == "__main__":
    sys.exit(main())
