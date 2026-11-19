"""Build the release zip for AppImage Runner.

Usage: python3 build_zip.py [output-path]

The zip holds the whole project folder (a top-level
appimage-run-helper/ directory) so it extracts as a folder the
user can open and double-click Install AppImage Runner.desktop
in. Written OUTSIDE the folder by default, next to it:
../appimage-run-helper-v0.1.0.zip.

Every file's stored mode is set explicitly: scripts AND .desktop
launchers get 0o100755, everything else 0o100644, and the
external_attr carries the regular-file type bits. GUI
extractors drop the execute bit when the type bits are missing,
and a non-executable .desktop double-clicks open in a text
editor instead of launching (the OST v22 lesson), so the
installer .desktop must extract executable.

The icon PNGs are gitignored build products: they are rendered
from assets/appimage.svg into a temp directory (QtSvg lives in
the venv's PySide6-Addons) and packed at assets/. If no Qt is
available the zip still builds, without PNGs, and the README
says the installer renders them on install.

Dev-only and secret-shaped files never ship: BUILD_REPORT.md,
install.log, .venv, __pycache__, and anything matched by the
.gitignore secrets section (.env, providers.json, key files).
"""

import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FOLDER_NAME = os.path.basename(ROOT)
sys.path.insert(0, ROOT)
from appimagehelper import __version__  # noqa: E402

ZIP_NAME = "appimage-run-helper-v%s.zip" % __version__

SCRIPTS = {
    "install.sh", "uninstall.sh", "run.sh", "run_tests.sh",
    "appimage-run", "appimage-make-runnable", "appimagehelper-cli",
}

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules",
             ".pytest_cache"}
SKIP_FILES = {"BUILD_REPORT.md", "install.log", ".qt-probe.err"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".zip"}
# Secret-shaped names: never ship, whatever the folder holds.
SECRET_NAMES = {"providers.json", ".env"}
SECRET_SUFFIXES = {".pem", ".key", ".env"}


def _mode_for(name):
    if name in SCRIPTS or name.endswith(".desktop"):
        return 0o100755
    return 0o100644


def _skipped(relpath):
    parts = relpath.split(os.sep)
    if any(part in SKIP_DIRS for part in parts):
        return True
    name = parts[-1]
    if name in SKIP_FILES or name in SECRET_NAMES:
        return True
    if name.startswith("id_rsa"):
        return True
    return os.path.splitext(name)[1] in SKIP_SUFFIXES | SECRET_SUFFIXES


def _render_icons():
    """Render the icon PNGs into a temp dir. Returns the dir, or
    None when no Qt is available (the zip then ships the SVG
    only and the installer renders the PNGs on install)."""
    candidates = []
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.exists(venv_py):
        candidates.append(venv_py)
    candidates.append(sys.executable)
    out_dir = tempfile.mkdtemp(prefix="appimage-icons-")
    for py in candidates:
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            result = subprocess.run(
                [py, os.path.join(ROOT, "render_icons.py"), out_dir],
                capture_output=True, text=True, env=env, timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and os.path.exists(
                os.path.join(out_dir, "appimage.png")):
            return out_dir
    return None


def build(output_path=None):
    if output_path is None:
        output_path = os.path.join(os.path.dirname(ROOT), ZIP_NAME)
    icon_dir = _render_icons()
    count = 0
    with zipfile.ZipFile(output_path, "w",
                         zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in SKIP_DIRS)
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ROOT)
                if _skipped(rel):
                    continue
                if rel.startswith("assets" + os.sep) and \
                        name.endswith(".png"):
                    continue  # PNGs come from the render step
                arcname = os.path.join(FOLDER_NAME, rel)
                info = zipfile.ZipInfo(arcname)
                info.external_attr = _mode_for(name) << 16
                info.create_system = 3
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
                count += 1
        if icon_dir is not None:
            for name in sorted(os.listdir(icon_dir)):
                if not name.endswith(".png"):
                    continue
                arcname = os.path.join(FOLDER_NAME, "assets", name)
                info = zipfile.ZipInfo(arcname)
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                with open(os.path.join(icon_dir, name),
                          "rb") as fh:
                    zf.writestr(info, fh.read())
                count += 1
    return output_path, count


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else None
    path, count = build(output)
    import hashlib
    with open(path, "rb") as fh:
        data = fh.read()
    print("Wrote %s" % path)
    print("Files: %d" % count)
    print("Bytes: %d" % len(data))
    print("SHA-256: %s" % hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
