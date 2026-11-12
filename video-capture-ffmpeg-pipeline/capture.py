#!/usr/bin/env python3
"""T14b — capture.py: capture helper for driving the real app.

Builds the ffmpeg x11grab command that records the real product in action
(S26 rule: drive the actual app — typing, windows opening, checkpoints
creating — no still screenshots, no generated video, no fake UI) and prints
the pre-capture checklist. Default is --dry-run: print the exact command
and the checklist, record nothing. Use --run to actually record (stop with
Ctrl+C or --duration).

Usage:
    capture.py --dry-run
    capture.py --dry-run --display :0 --size 1920x1080 --framerate 30
    capture.py --run --output raw-capture.mp4 --duration 60
    capture.py --checklist
    capture.py --check
"""
import argparse
import os
import shutil
import subprocess
import sys

CHECKLIST = """\
CAPTURE CHECKLIST — drive the real app
  [ ] The app is the REAL build, launched normally (not a mock, not a screenshot)
  [ ] Desktop is clean: no personal files, notifications, or other windows visible
  [ ] Window sized to the capture region; nothing clipped
  [ ] Sound: real licensed recordings only, with CC BY credit lines ready.
      Never synthesized audio. Never his music unless he named the track
      for this use.
  [ ] Plan the beats before recording: hook (result in frame 1), 2-3 real
      UI beats for proof, CTA at the end
  [ ] No people, no hands in frame
  [ ] Record longer than needed — the cutter takes the best 15s
  [ ] After capture: cut with cut_video.py (15s structure, -14 LUFS,
      fresh filename per cut)
"""


def build_command(display, size, framerate, output, duration, audio):
    cmd = ["ffmpeg", "-y", "-video_size", size, "-framerate", str(framerate),
           "-f", "x11grab", "-i", "%s+0,0" % display]
    if audio:
        cmd += ["-f", "pulse", "-i", "default"]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += [output]
    return cmd


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Capture helper: build the ffmpeg x11grab command for "
                    "recording the real app, print the checklist.")
    ap.add_argument("--display", default=":0",
                    help="X display to grab (default :0)")
    ap.add_argument("--size", default="1920x1080",
                    help="capture size WxH (default 1920x1080)")
    ap.add_argument("--framerate", type=int, default=30)
    ap.add_argument("--output", default="raw-capture.mp4")
    ap.add_argument("--duration", type=int,
                    help="record N seconds then stop (else Ctrl+C)")
    ap.add_argument("--no-audio", action="store_true",
                    help="capture video only (no pulse audio input)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the command + checklist, record nothing")
    ap.add_argument("--run", action="store_true",
                    help="actually run the capture")
    ap.add_argument("--checklist", action="store_true",
                    help="print only the checklist")
    ap.add_argument("--check", action="store_true",
                    help="report ffmpeg + display availability")
    args = ap.parse_args(argv)

    if args.checklist:
        print(CHECKLIST)
        return 0
    if args.check:
        print("ffmpeg: %s" % (shutil.which("ffmpeg") or "NOT FOUND"))
        print("DISPLAY: %s" % os.environ.get("DISPLAY", "(unset)"))
        print("x11grab needs a running X server on the capture display.")
        return 0 if shutil.which("ffmpeg") else 1
    if args.run and args.dry_run:
        ap.error("--run and --dry-run conflict")
    if not args.run:
        args.dry_run = True  # default: print, record nothing

    cmd = build_command(args.display, args.size, args.framerate,
                        args.output, args.duration, not args.no_audio)
    print(" ".join(cmd))
    print()
    print(CHECKLIST)
    if args.dry_run:
        print("DRY RUN — nothing recorded. Re-run with --run to capture.")
        return 0
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not found on PATH.", file=sys.stderr)
        return 1
    print("Recording to %s (Ctrl+C to stop)..."
          % args.output)
    try:
        p = subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
