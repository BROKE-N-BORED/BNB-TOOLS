#!/usr/bin/env python3
"""Build song-key-bpm-v0.1.0.zip for verification / release.

Correct exec bits via external_attr: 0o100755 for scripts, 0o100644
for plain files. Bare 0o755 (no file-type bits) extracts fine under
the `unzip` CLI but GUI extractors drop the execute bit.

The icon PNGs are rendered into a temp folder (in a subprocess, so
a render crash fails the build instead of the caller) and packed
into the zip at assets/ - they never land in the tree.

The zip is written OUTSIDE this folder by default, so the folder
stays all UTF-8 text (snapshot pushes cannot carry binaries).
Use --out to pick a different destination.

The icon render needs the Qt environment: run with
LD_LIBRARY_PATH pointed at the Qt libs and QT_QPA_PLATFORM set
to offscreen, or the render fails on the xcb platform plugin.
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "song-key-bpm-v0.1.0.zip"

SCRIPTS = {"install.sh", "run.sh", "song-key-bpm",
           "song-key-analyze", "song-key-export", "songkey-cli",
           "uninstall.sh", "run_tests.sh", "build_zip.py",
           "render_icons.py"}

SKIP_DIRS = {"__pycache__", ".forge", ".venv", "venv", ".git", "logs"}
SKIP_FILES = {".DS_Store", "BUILD_REPORT.md", "install.log",
              ".qt-probe.err"}


def collect() -> list[Path]:
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_dir():
            continue
        if path.name == ZIP_NAME:
            continue
        if path.name in SKIP_FILES or path.suffix in (".zip", ".pyc"):
            continue
        # Rendered icons are packed fresh by render_icons()
        # below; a PNG already sitting in assets/ (an extracted
        # copy, or a local render) would otherwise land in the
        # zip twice under the same name. (Coordinator fix: the
        # fresh-unzip suite run caught 57 entries / 50 unique.)
        if (path.suffix == ".png"
                and path.parent.name == "assets"):
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(HERE).parts):
            continue
        files.append(path)
    return files


def render_icons(tmpdir: Path) -> list[Path]:
    """Render the PNGs into tmpdir/assets/ via a subprocess."""
    out_dir = tmpdir / "assets"
    proc = subprocess.run(
        [sys.executable, str(HERE / "render_icons.py"),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit("icon render failed; zip not built")
    return sorted(out_dir.glob("songkey*.png"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Song Key BPM release zip.")
    parser.add_argument("--out", default=None,
                        help="zip destination (default: ../%s)"
                        % ZIP_NAME)
    args = parser.parse_args()
    out = Path(args.out) if args.out else HERE.parent / ZIP_NAME
    files = collect()
    with tempfile.TemporaryDirectory() as tmp:
        icons = render_icons(Path(tmp))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                rel = path.relative_to(HERE).as_posix()
                info = zipfile.ZipInfo(rel)
                mode = 0o100755 if path.name in SCRIPTS else 0o100644
                info.external_attr = mode << 16
                zf.writestr(info, path.read_bytes())
            for icon in icons:
                rel = "assets/" + icon.name
                info = zipfile.ZipInfo(rel)
                info.external_attr = 0o100644 << 16
                zf.writestr(info, icon.read_bytes())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("wrote %s (%d bytes, %d files + %d icons)"
          % (out, out.stat().st_size, len(files), len(icons)))
    print("SHA-256: %s" % digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
