#!/usr/bin/env python3
"""Smoke test for T15 compress-to-size.

Verifies the bitrate arithmetic by hand, the --dry-run (print-only) output,
and — ffmpeg present — a real compress of a generated clip that must land
under the cap.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "compress_to_size.py"
sys.path.insert(0, str(HERE.parent))
import compress_to_size as c2s  # noqa: E402


def run(*args, timeout=180):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    # Hand-check the math: 3720s video, 100 MB cap, margin 0.88, audio 128.
    # aim = 100,000,000 * 0.88 = 88,000,000 bytes
    # total kbps = 88,000,000 * 8 / 3720 / 1000 = 189.247...
    # video kbps = 189.247 - 128 = 61.247...
    plan = c2s.bitrate_math(3720, 100)
    print("== math: aim=%.0f B total=%.3f kbps video=%.3f kbps"
          % (plan["aim_bytes"], plan["total_kbps"], plan["video_kbps"]))
    if plan["aim_bytes"] != 88_000_000:
        fails.append("aim bytes wrong: %r" % plan["aim_bytes"])
    if abs(plan["total_kbps"] - 88_000_000 * 8 / 3720 / 1000) > 0.001:
        fails.append("total kbps wrong: %r" % plan["total_kbps"])
    if abs(plan["video_kbps"] - (plan["total_kbps"] - 128)) > 0.001:
        fails.append("video kbps wrong: %r" % plan["video_kbps"])
    # 60s clip at 100 MB: total = 88,000,000*8/60/1000 = 11,733.33 kbps
    plan60 = c2s.bitrate_math(60, 100)
    if abs(plan60["total_kbps"] - 11733.333) > 0.01:
        fails.append("60s total kbps wrong: %r" % plan60["total_kbps"])
    print("== 60s clip: total=%.1f kbps video=%.1f kbps"
          % (plan60["total_kbps"], plan60["video_kbps"]))

    # Print-only run on a real file (no ffmpeg needed with --duration).
    tmp = Path(tempfile.mkdtemp(prefix="t15-smoke-"))
    dummy = tmp / "dummy.mp4"
    dummy.write_bytes(b"not a real video")
    p = run(str(dummy), "100", "--duration", "3720")
    print("== print-only exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0 or "PRINT ONLY" not in p.stdout:
        fails.append("print-only run failed")
    if "video 61 kbps" not in p.stdout:
        fails.append("print-only output missing the hand-checked bitrate")

    # Real compress, if ffmpeg exists.
    have_ffmpeg = subprocess.run(["which", "ffmpeg"],
                                 capture_output=True).returncode == 0
    print("== ffmpeg present: %s" % have_ffmpeg)
    if have_ffmpeg:
        src = tmp / "clip.mp4"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "testsrc=duration=30:size=640x360:rate=30",
                            "-f", "lavfi",
                            "-i", "sine=frequency=440:duration=30",
                            "-shortest", "-c:v", "libx264", "-c:a", "aac",
                            str(src)], capture_output=True, text=True)
        if r.returncode != 0:
            fails.append("could not generate test clip: %s" % r.stderr)
        else:
            orig_mb = src.stat().st_size / 1_000_000
            # 30s clip, 1 MB cap -> aim 0.88 MB -> total ~234.7 kbps,
            # video ~106.7 kbps. Must land under 1 MB.
            p = run(str(src), "1", "--run")
            print("== real compress exit=%d" % p.returncode)
            print(p.stdout)
            outs = sorted(tmp.glob("clip-1MB.mp4"))
            if p.returncode != 0 or not outs:
                fails.append("real compress failed: %s" % p.stderr[-500:])
            else:
                got_mb = outs[0].stat().st_size / 1_000_000
                print("== original %.2f MB -> compressed %.2f MB (cap 1 MB)"
                      % (orig_mb, got_mb))
                if got_mb > 1.0:
                    fails.append("compressed file over cap: %.2f MB"
                                 % got_mb)
            # Audio-only extraction.
            p = run(str(src), "1", "--audio-only", "--run")
            print("== audio-only exit=%d" % p.returncode)
            if p.returncode != 0 or not list(tmp.glob("clip-audio-only.m4a")):
                fails.append("audio-only extraction failed: %s"
                             % p.stderr[-500:])
    else:
        print("ffmpeg absent — real-compress path not exercised")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
