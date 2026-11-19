#!/usr/bin/env python3
"""Build manual-pdf-builder-v0.1.0.zip for verification / release.

Correct exec bits via external_attr: 0o100755 for scripts, 0o100644
for plain files, 0o40755 for directories, with the file-type bits
included and create_system set to 3 (Unix) on every entry. Bare
0o755 (no file-type bits) extracts fine under the `unzip` CLI but
GUI extractors drop the execute bit.

The zip is written OUTSIDE this folder by default, so the folder
stays all UTF-8 text (snapshot pushes cannot carry binaries).
Use --out to pick a different destination.
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "manual-pdf-builder-v0.1.0.zip"

SCRIPTS = {"manual_pdf.py", "demo.py", "run_tests.sh", "build_zip.py"}

SKIP_DIRS = {"__pycache__", ".forge", ".venv", "venv", ".git", "logs"}
SKIP_FILES = {".DS_Store", "BUILD_REPORT.md", "install.log"}


def collect():
    """(files, dirs): all shippable files plus their parent dirs,
    as paths relative to this folder, sorted."""
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_dir():
            continue
        if path.name == ZIP_NAME:
            continue
        if path.name in SKIP_FILES or path.suffix in (".zip", ".pyc"):
            continue
        if any(part in SKIP_DIRS
               for part in path.relative_to(HERE).parts):
            continue
        files.append(path.relative_to(HERE))
    dirs = set()
    for rel in files:
        parent = rel.parent
        while str(parent) not in (".", ""):
            dirs.add(parent)
            parent = parent.parent
    return files, sorted(dirs)


def main():
    parser = argparse.ArgumentParser(
        description="Build the manual-pdf-builder release zip.")
    parser.add_argument("--out", default=None,
                        help="zip destination (default: ../%s)"
                        % ZIP_NAME)
    args = parser.parse_args()
    out = Path(args.out) if args.out else HERE.parent / ZIP_NAME
    files, dirs = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in dirs:
            info = zipfile.ZipInfo(rel.as_posix() + "/")
            info.create_system = 3
            info.external_attr = 0o40755 << 16
            zf.writestr(info, b"")
        for rel in files:
            info = zipfile.ZipInfo(rel.as_posix())
            info.create_system = 3
            mode = 0o100755 if rel.name in SCRIPTS else 0o100644
            info.external_attr = mode << 16
            zf.writestr(info, (HERE / rel).read_bytes())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("wrote %s (%d bytes, %d files, %d dirs)"
          % (out, out.stat().st_size, len(files), len(dirs)))
    print("SHA-256: %s" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
