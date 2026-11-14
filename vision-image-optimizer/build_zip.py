#!/usr/bin/env python3
"""Build vision-image-optimizer-v0.1.0.zip for verification / release.

Correct exec bits via external_attr: 0o100755 for scripts, 0o100644
for plain files. Bare 0o755 (no file-type bits) extracts fine under
the `unzip` CLI but GUI extractors drop the execute bit.

The icon PNGs are rendered into a temp folder (in a subprocess, so
a render crash fails the build instead of the caller) and packed
into the zip at assets/ — they never land in the tree.
"""
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "vision-image-optimizer-v0.1.0.zip"

SCRIPTS = {"install.sh", "run.sh", "optimizer-cli", "uninstall.sh",
           "run_tests.sh", "build_zip.py", "render_icons.py"}

SKIP_DIRS = {"__pycache__", ".forge", ".venv", "venv", ".git", "logs"}
SKIP_FILES = {".DS_Store", "BUILD_REPORT.md"}


def collect() -> list[Path]:
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_dir():
            continue
        if path.name == ZIP_NAME:
            continue
        if path.name in SKIP_FILES or path.suffix == ".zip":
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
    return sorted(out_dir.glob("vision*.png"))


def main() -> int:
    files = collect()
    out = HERE / ZIP_NAME
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
