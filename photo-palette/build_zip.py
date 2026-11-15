#!/usr/bin/env python3
"""Build photo-palette-v0.1.0.zip for verification / release.

Correct exec bits via external_attr: 0o100755 for scripts, 0o100644
for plain files. Bare 0o755 (no file-type bits) extracts fine under
the `unzip` CLI but GUI extractors drop the execute bit.

The zip is written OUTSIDE this folder by default, so the folder
stays all UTF-8 text (snapshot pushes cannot carry binaries).
Use --out to pick a different destination.

BUILD_REPORT.md is excluded: it is a build record, not part of
the shipped tool.
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "photo-palette-v0.1.0.zip"

SCRIPTS = {"photo_palette.py", "run_tests.sh", "build_zip.py"}

SKIP_DIRS = {"__pycache__", ".forge", ".venv", "venv", ".git", "logs"}
SKIP_FILES = {".DS_Store", "BUILD_REPORT.md"}


def collect() -> list[Path]:
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_dir():
            continue
        if path.name == ZIP_NAME:
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in (".zip", ".pyc", ".png"):
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(HERE).parts):
            continue
        files.append(path)
    return files


def mode_for(path: Path) -> int:
    return 0o100755 if path.name in SCRIPTS else 0o100644


def verify(out: Path, files: list[Path]) -> None:
    """Reopen the zip and prove every entry carries its mode."""
    with zipfile.ZipFile(out) as zf:
        entries = {info.filename: info for info in zf.infolist()}
    if len(entries) != len(files):
        raise SystemExit("zip has %d entries, expected %d"
                         % (len(entries), len(files)))
    for path in files:
        rel = path.relative_to(HERE).as_posix()
        info = entries.get(rel)
        if info is None:
            raise SystemExit("zip is missing %s" % rel)
        if info.create_system != 3:
            raise SystemExit("%s: create_system is %d, not 3 (Unix)"
                             % (rel, info.create_system))
        mode = info.external_attr >> 16
        if mode != mode_for(path):
            raise SystemExit("%s: mode %s, expected %s"
                             % (rel, oct(mode), oct(mode_for(path))))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Photo Palette release zip.")
    parser.add_argument("--out", default=None,
                        help="zip destination (default: ../%s)"
                        % ZIP_NAME)
    args = parser.parse_args()
    out = Path(args.out) if args.out else HERE.parent / ZIP_NAME
    files = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(HERE).as_posix()
            info = zipfile.ZipInfo(rel)
            info.create_system = 3
            info.external_attr = mode_for(path) << 16
            zf.writestr(info, path.read_bytes())
    verify(out, files)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("wrote %s (%d bytes, %d files, modes verified)"
          % (out, out.stat().st_size, len(files)))
    print("SHA-256: %s" % digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
