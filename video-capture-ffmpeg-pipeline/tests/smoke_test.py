#!/usr/bin/env python3
"""Smoke test for T14 video-capture-ffmpeg-pipeline.

If ffmpeg exists: generate a 20s test clip (testsrc video + sine audio),
cut it to the 15s structure, and verify the output (duration ~15s, chapters
present, fresh timestamped name, second cut gets a different name).
Always: --help on both scripts, capture --dry-run + --checklist, and the
cut --dry-run command builder.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUT = HERE.parent / "cut_video.py"
CAP = HERE.parent / "capture.py"


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    for script in (CUT, CAP):
        p = run([sys.executable, str(script), "--help"])
        print("== %s --help exit=%d" % (script.name, p.returncode))
        if p.returncode != 0:
            fails.append("%s --help failed" % script.name)

    p = run([sys.executable, str(CAP), "--dry-run", "--size", "1280x720"])
    print("== capture --dry-run exit=%d" % p.returncode)
    print(p.stdout)
    if "x11grab" not in p.stdout or ":0+0,0" not in p.stdout:
        fails.append("capture --dry-run did not print an x11grab command")
    if "CAPTURE CHECKLIST" not in p.stdout:
        fails.append("capture --dry-run did not print the checklist")

    p = run([sys.executable, str(CAP), "--check"])
    print("== capture --check exit=%d\n%s" % (p.returncode, p.stdout))

    have_ffmpeg = run(["which", "ffmpeg"]).returncode == 0
    print("== ffmpeg present: %s" % have_ffmpeg)
    if not have_ffmpeg:
        print("ffmpeg absent — cut test limited to --dry-run command "
              "builder (see below)")
    tmp = Path(tempfile.mkdtemp(prefix="t14-smoke-"))
    if have_ffmpeg:
        src = tmp / "raw.mp4"
        p = run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "testsrc=duration=20:size=640x360:rate=30",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                 "-shortest", "-c:v", "libx264", "-c:a", "aac",
                 str(src)])
        if p.returncode != 0:
            fails.append("could not generate test clip: %s" % p.stderr)
        else:
            edit = {"source": str(src), "name": "smoke-ad", "cuts": [
                {"section": "hook", "start": 0.0, "end": 2.0},
                {"section": "proof", "start": 5.0, "end": 13.0},
                {"section": "trust", "start": 14.0, "end": 16.0},
                {"section": "cta", "start": 17.0, "end": 20.0}]}
            edit_path = tmp / "edit.json"
            edit_path.write_text(json.dumps(edit))
            out_dir = tmp / "cuts"
            p = run([sys.executable, str(CUT), str(edit_path),
                     "--out-dir", str(out_dir)])
            print("== cut exit=%d" % p.returncode)
            print(p.stdout)
            if p.returncode != 0:
                fails.append("cut failed: %s" % p.stderr[-500:])
            outs = sorted(out_dir.glob("smoke-ad-*.mp4"))
            if not outs:
                fails.append("cut produced no output file")
            else:
                out = outs[0]
                print("== output: %s (%d bytes)"
                      % (out.name, out.stat().st_size))
                p = run(["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-show_entries",
                         "chapter_tags=title",
                         "-of", "default=noprint_wrappers=1", str(out)])
                print(p.stdout)
                dur = None
                for ln in p.stdout.splitlines():
                    if ln.startswith("duration="):
                        dur = float(ln.split("=", 1)[1])
                if dur is None or abs(dur - 15.0) > 0.2:
                    fails.append("output duration should be ~15s, got %r"
                                 % dur)
                for section in ("hook", "proof", "trust", "cta"):
                    if ("title=" + section) not in p.stdout:
                        fails.append("missing chapter marker: %s" % section)
                # Fresh filename: a second cut must not overwrite the first.
                p2 = run([sys.executable, str(CUT), str(edit_path),
                          "--out-dir", str(out_dir)])
                outs2 = sorted(out_dir.glob("smoke-ad-*.mp4"))
                if len(outs2) != 2:
                    fails.append("second cut should create a second file, "
                                 "not overwrite (got %d)" % len(outs2))
                else:
                    print("== second cut: %s (no overwrite)"
                          % outs2[-1].name)
    else:
        # No ffmpeg: exercise the edit-list parser + command builder only.
        edit = {"source": "missing.mp4", "name": "x", "cuts": [
            {"section": "hook", "start": 0, "end": 2}]}
        edit_path = tmp / "edit.json"
        edit_path.write_text(json.dumps(edit))
        p = run([sys.executable, str(CUT), str(edit_path), "--dry-run"])
        if p.returncode == 0:
            fails.append("cut --dry-run should fail honestly without ffmpeg")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
