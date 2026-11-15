#!/usr/bin/env python3
"""Build battery-waiter-v0.1.0.zip for verification / release.

Correct exec bits via external_attr: 0o100755 for scripts, 0o100644
for plain files. Bare 0o755 (no file-type bits) extracts fine under
the `unzip` CLI but GUI extractors drop the execute bit.

The zip is written OUTSIDE this folder by default, so the folder
stays all UTF-8 text (snapshot pushes cannot carry binaries).
Use --out to pick a different destination.

BUILD_REPORT.md is excluded: it is a build record, not a shipped
file. __pycache__, logs, and stray zips are excluded too.
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "battery-waiter-v0.1.0.zip"

SCRIPTS = {"battery_waiter.py", "run_tests.sh", "build_zip.py"}

SKIP_DIRS = {"__pycache__", ".forge", ".venv", "venv", ".git", "logs"}
SKIP_FILES = {".DS_Store", "BUILD_REPORT.md"}


def collect() -> list[Path]:
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_dir():
            continue
        if path.name == ZIP_NAME:
            continue
        if path.name in SKIP_FILES or path.suffix in (".zip", ".pyc"):
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(HERE).parts):
            continue
        files.append(path)
    return files


def expected_mode(path: Path) -> int:
    return 0o100755 if path.name in SCRIPTS else 0o100644


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the battery-waiter release zip.")
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
            info.external_attr = expected_mode(path) << 16
            zf.writestr(info, path.read_bytes())
    # Verify the stored modes by reopening the zip.
    with zipfile.ZipFile(out, "r") as zf:
        infos = {info.filename: (info.external_attr >> 16)
                 for info in zf.infolist()}
    for path in files:
        rel = path.relative_to(HERE).as_posix()
        stored = infos.get(rel)
        if stored != expected_mode(path):
            print("mode mismatch in zip for %s: stored %o, want %o"
                  % (rel, stored or 0, expected_mode(path)),
                  file=sys.stderr)
            return 1
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("wrote %s (%d bytes, %d files, modes verified)"
          % (out, out.stat().st_size, len(files)))
    print("SHA-256: %s" % digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
