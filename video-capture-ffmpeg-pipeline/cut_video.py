#!/usr/bin/env python3
"""T14a — cut_video.py: cut + loudness-normalize a promo video.

Takes raw captured footage of the REAL product and cuts it to the
sellable-ads 15s structure (from BNB SKILLS S26):

    hook  0-2s    the result in frame 1
    proof 2-10s   2-3 real UI beats
    trust 10-12s  only if verifiable
    CTA   12-15s  "Free download — link in bio"

Input is an edit list (JSON): source ranges mapped onto the 15s structure.
Output is loudness-normalized to -14 LUFS (two-pass ffmpeg loudnorm) with
chapter markers for hook/proof/trust/cta, under a fresh timestamped
filename — never overwriting an earlier cut, so nobody ever watches a
cached old version.

Edit list format:
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

Cut durations should total 15.0s (hook 2 + proof 8 + trust 2 + cta 3);
the tool warns (does not fail) if they don't, and reports the actual total.

Usage:
    cut_video.py edit-list.json
    cut_video.py edit-list.json --dry-run     # print the ffmpeg commands
    cut_video.py edit-list.json --out-dir cuts/

Requires ffmpeg + ffprobe on PATH. Exit 0 = cut written, 1 = failure.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

TARGET_LUFS = -14.0
TARGET_TP = -1.5
TARGET_LRA = 11.0


def have(cmd):
    return shutil.which(cmd) is not None


def run(cmd, capture=False):
    return subprocess.run(cmd, capture_output=capture, text=True)


def probe_duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", path], capture=True)
    if p.returncode != 0:
        raise RuntimeError("ffprobe failed on %s: %s"
                           % (path, p.stderr.strip()))
    return float(p.stdout.strip())


def fresh_name(out_dir, base, ext=".mp4"):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "%s-%s%s" % (base, stamp, ext)
    n = 2
    while os.path.exists(os.path.join(out_dir, name)):
        name = "%s-%s-%d%s" % (base, stamp, n, ext)
        n += 1
    return os.path.join(out_dir, name)


def build_filter(cuts, loudnorm_args=None):
    """Build the trim/concat filter + chapter metadata for the cut list.

    loudnorm runs INSIDE the filter graph (a simple -af cannot be combined
    with -filter_complex for the same stream). Returns (filter string,
    chapters, audio output label).
    """
    parts = []
    for i, c in enumerate(cuts):
        parts.append(
            "[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS[v%d]"
            % (c["start"], c["end"], i))
        parts.append(
            "[0:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS[a%d]"
            % (c["start"], c["end"], i))
    v = "".join("[v%d]" % i for i in range(len(cuts)))
    a = "".join("[a%d]" % i for i in range(len(cuts)))
    parts.append("%sconcat=n=%d:v=1:a=0[outv]" % (v, len(cuts)))
    parts.append("%sconcat=n=%d:v=0:a=1[outa]" % (a, len(cuts)))
    audio_label = "[outa]"
    if loudnorm_args:
        parts.append("[outa]loudnorm=%s[aout]" % loudnorm_args)
        audio_label = "[aout]"
    chapters = []
    t = 0.0
    for c in cuts:
        dur = c["end"] - c["start"]
        chapters.append((t, t + dur, c["section"]))
        t += dur
    return ";".join(parts), chapters, audio_label


def chapter_metadata(chapters):
    lines = [";FFMETADATA1"]
    for start, end, title in chapters:
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append("START=%d" % round(start * 1000))
        lines.append("END=%d" % round(end * 1000))
        lines.append("title=%s" % title)
    return "\n".join(lines) + "\n"


def loudnorm_measure(cmd_base):
    """First loudnorm pass: measure, parse the JSON summary.

    loudnorm prints its summary at info level, so this pass runs with
    -v info (the encode pass keeps -v error).
    """
    cmd = list(cmd_base)
    if "-v" in cmd:
        cmd[cmd.index("-v") + 1] = "info"
    cmd += ["-f", "null", "-"]
    p = run(cmd, capture=True)
    if p.returncode != 0:
        raise RuntimeError("loudnorm measure pass failed:\n%s"
                           % p.stderr[-1000:])
    text = p.stderr
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("loudnorm measure pass printed no JSON summary")
    return json.loads(text[start:end + 1])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cut raw footage to the 15s sellable-ads structure, "
                    "loudness-normalize to -14 LUFS, fresh filename.")
    ap.add_argument("edit_list", help="edit-list JSON file")
    ap.add_argument("--out-dir", default=".",
                    help="output directory (default: current dir)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ffmpeg commands, run nothing")
    args = ap.parse_args(argv)

    if not have("ffmpeg"):
        print("error: ffmpeg not found on PATH — install it "
              "(`sudo apt install ffmpeg`) or run on a machine that has it.",
              file=sys.stderr)
        return 1
    if not have("ffprobe"):
        print("error: ffprobe not found on PATH.", file=sys.stderr)
        return 1
    if not os.path.isfile(args.edit_list):
        print("error: no such file: %s" % args.edit_list, file=sys.stderr)
        return 2
    with open(args.edit_list) as f:
        edit = json.load(f)

    source = edit["source"]
    if not os.path.isfile(source):
        print("error: source video not found: %s" % source, file=sys.stderr)
        return 2
    cuts = edit["cuts"]
    total = sum(c["end"] - c["start"] for c in cuts)
    print("source: %s (%.1fs)" % (source, probe_duration(source)))
    print("cuts: %s" % ", ".join(
        "%s %.1f-%.1fs" % (c["section"], c["start"], c["end"])
        for c in cuts))
    print("total cut length: %.1fs (target 15.0s)" % total)
    if abs(total - 15.0) > 0.05:
        print("warning: cut totals %.1fs, not 15.0s — the 15s structure "
              "wants hook 2 + proof 8 + trust 2 + cta 3" % total)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = fresh_name(args.out_dir, edit.get("name", "cut"))
    meta_path = os.path.join(args.out_dir, ".chapters-%s.txt"
                             % os.path.basename(out_path))
    _filt, chapters, _alabel = build_filter(cuts)
    with open(meta_path, "w") as f:
        f.write(chapter_metadata(chapters))

    def command_for(loudnorm_args, outputs):
        filt, _ch, alabel = build_filter(cuts, loudnorm_args)
        return (["ffmpeg", "-y", "-v", "error", "-i", source,
                 "-i", meta_path, "-map_metadata", "1",
                 "-filter_complex", filt,
                 "-map", "[outv]", "-map", alabel,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
                + outputs)

    measure_args = ("I=%.1f:TP=%.1f:LRA=%.1f:print_format=json"
                    % (TARGET_LUFS, TARGET_TP, TARGET_LRA))

    if args.dry_run:
        print("\nDRY RUN — commands that would run:")
        print("  measure: " + " ".join(
            command_for(measure_args, ["-f", "null", "-"])))
        print("  encode:  " + " ".join(
            command_for("I=-14:TP=-1.5:LRA=11:measured_*=<from measure "
                        "pass>:linear=true", [out_path])))
        print("  output would be: %s" % out_path)
        os.unlink(meta_path)
        return 0

    print("measuring loudness (pass 1)...")
    measured = loudnorm_measure(command_for(measure_args, []))
    print("  input: I=%.1f LUFS, TP=%.1f, LRA=%.1f, threshold=%.1f"
          % (float(measured["input_i"]), float(measured["input_tp"]),
             float(measured["input_lra"]),
             float(measured["input_thresh"])))
    encode_args = ("I=%.1f:TP=%.1f:LRA=%.1f:"
                   "measured_I=%s:measured_TP=%s:measured_LRA=%s:"
                   "measured_thresh=%s:offset=%s:linear=true"
                   % (TARGET_LUFS, TARGET_TP, TARGET_LRA,
                      measured["input_i"], measured["input_tp"],
                      measured["input_lra"], measured["input_thresh"],
                      measured["target_offset"]))
    print("encoding (pass 2)...")
    p = run(command_for(encode_args, [out_path]), capture=True)
    os.unlink(meta_path)
    if p.returncode != 0:
        print("error: encode failed:\n%s" % p.stderr[-1000:],
              file=sys.stderr)
        return 1
    dur = probe_duration(out_path)
    size = os.path.getsize(out_path)
    print("done: %s" % out_path)
    print("  duration %.1fs, %d bytes, normalized to %.0f LUFS, "
          "%d chapter markers" % (dur, size, TARGET_LUFS, len(chapters)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
