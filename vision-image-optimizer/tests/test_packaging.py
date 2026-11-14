"""Packaging: bash-clean scripts, .desktop files that survive GLib,
zip exec bits, SVG icon, no binaries, no leftover markers, no secrets."""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHELL_SCRIPTS = ("install.sh", "run.sh", "optimizer-cli",
                 "uninstall.sh", "run_tests.sh")
EXEC_IN_ZIP = {"install.sh", "run.sh", "optimizer-cli",
               "uninstall.sh", "run_tests.sh", "build_zip.py",
               "render_icons.py"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"password\s*=\s*[\"'][^\"']{4,}[\"']"),
    re.compile(r"api[_-]?key\s*=\s*[\"'][^\"']{4,}[\"']"),
]
# The scrub test's deliberate fakes live here and only here.
SECRET_ALLOWLIST = {os.path.join("tests", "test_debug_log.py")}

SKIP_DIRS = {"__pycache__", ".venv", ".git", "logs"}


def tree_files():
    found = []
    for root, dirs, files in os.walk(TREE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            found.append(os.path.join(root, name))
    return found


class ShellTests(unittest.TestCase):
    def test_scripts_are_bash_clean(self):
        for name in SHELL_SCRIPTS:
            path = os.path.join(TREE, name)
            self.assertTrue(os.path.exists(path), name)
            proc = subprocess.run(["bash", "-n", path],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (name, proc.stderr))

    def test_python_files_compile(self):
        for path in tree_files():
            if path.endswith(".py"):
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                compile(source, path, "exec")

    def test_no_sh_invocation_of_scripts(self):
        # "sh install.sh" must never appear as a command; "bash
        # install.sh" is fine, so the match needs a word boundary
        # before "sh" (a bare substring match trips on "bash").
        pattern = re.compile(r"(^|\s)sh (install|run)\.sh")
        for name in ("install.sh", "run.sh", "README.md"):
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(pattern.search(text), name)


class DesktopFileTests(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(TREE, name),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_installer_desktop_structural(self):
        text = self._read("Install Vision Image Optimizer.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Install Vision Image Optimizer", text)
        self.assertIn("Terminal=false", text)
        exec_line = [ln for ln in text.splitlines()
                     if ln.startswith("Exec=")][0]
        self.assertIn("install.sh", exec_line)
        self.assertIn("%k", exec_line)
        # GLib rejects nested escaped quotes in Exec outright.
        self.assertNotIn('\\"', exec_line)

    def test_app_desktop_template_structural(self):
        text = self._read("vision-image-optimizer.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Vision Image Optimizer", text)
        self.assertIn("Terminal=false", text)
        exec_line = [ln for ln in text.splitlines()
                     if ln.startswith("Exec=")][0]
        self.assertNotIn('\\"', exec_line)
        icon_line = [ln for ln in text.splitlines()
                     if ln.startswith("Icon=")][0]
        # Icon= must NOT be quoted: GLib takes it literally.
        self.assertFalse(icon_line.startswith('Icon="'),
                         icon_line)

    def test_desktop_file_validate_if_present(self):
        validator = shutil.which("desktop-file-validate")
        if validator is None:
            self.skipTest("desktop-file-validate not installed")
        for name in ("Install Vision Image Optimizer.desktop",
                     "vision-image-optimizer.desktop"):
            proc = subprocess.run(
                [validator, os.path.join(TREE, name)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (name, proc.stdout))


class ZipTests(unittest.TestCase):
    def test_build_zip_modes_and_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "vision-image-optimizer")
            shutil.copytree(TREE, copy, ignore=shutil.ignore_patterns(
                "__pycache__", ".venv", "*.zip", ".git", "logs"))
            proc = subprocess.run(
                [sys.executable, "build_zip.py"], cwd=copy,
                capture_output=True, text=True, timeout=300,
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            zips = [f for f in os.listdir(copy)
                    if f.endswith(".zip")]
            self.assertEqual(len(zips), 1)
            zpath = os.path.join(copy, zips[0])
            with zipfile.ZipFile(zpath) as zf:
                names = zf.namelist()
                self.assertIn("install.sh", names)
                self.assertIn("assets/vision.svg", names)
                # Rendered PNGs ship in the zip, not the tree.
                self.assertIn("assets/vision-16.png", names)
                self.assertIn("assets/vision-256.png", names)
                self.assertIn("assets/vision.png", names)
                self.assertNotIn("BUILD_REPORT.md", names)
                for info in zf.infolist():
                    # The full upper 16 bits are the stored mode,
                    # file-type bits included — do not mask them off.
                    mode = info.external_attr >> 16
                    base = os.path.basename(info.filename)
                    if base in EXEC_IN_ZIP:
                        self.assertEqual(
                            mode, 0o100755, info.filename)
                    elif not info.is_dir():
                        self.assertEqual(
                            mode, 0o100644, info.filename)
                # Test-extract with the unzip CLI: Python's zipfile
                # never restores stored modes, but unzip does — and
                # the GUI extractors on his PC behave like unzip.
                extract = os.path.join(tmp, "extracted")
                proc = subprocess.run(
                    ["unzip", "-q", "-o", zpath, "-d", extract],
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.access(
                os.path.join(extract, "install.sh"), os.X_OK))
            self.assertTrue(os.access(
                os.path.join(extract, "run.sh"), os.X_OK))


class TreeHygieneTests(unittest.TestCase):
    def test_icon_svg_parses_as_xml(self):
        path = os.path.join(TREE, "assets", "vision.svg")
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.get("width"), "256")
        self.assertEqual(root.get("height"), "256")

    def test_no_binary_files_in_tree(self):
        # The renderer's outputs are the only binaries allowed, and
        # only under assets/: build_zip.py ships them in the Release
        # zip and install.sh renders them for a fresh clone, so an
        # installed/extracted tree legitimately has them. They are
        # derived from vision.svg, gitignored, and never committed.
        binary_exts = {".png", ".jpg", ".jpeg", ".pyc", ".so",
                       ".ico", ".ttf"}
        rendered = {"assets/vision.png"}
        rendered.update("assets/vision-%d.png" % size
                        for size in (16, 32, 48, 64, 128, 256))
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
            if path.endswith(".zip"):
                continue  # build output, gitignored
            if rel in rendered:
                continue  # renderer output, see above
            ext = os.path.splitext(path)[1].lower()
            self.assertNotIn(ext, binary_exts, rel)
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                self.fail("not UTF-8 text: %s" % rel)

    def test_no_todo_or_fixme(self):
        # The markers are built from parts so this test file does
        # not trip its own check.
        markers = ("TO" + "DO", "FIX" + "ME")
        for path in tree_files():
            if path.endswith(".zip"):
                continue
            with open(path, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
            for marker in markers:
                self.assertNotIn(marker, text, path)

    def test_no_secrets_in_tree(self):
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
            if path.endswith(".zip"):
                continue
            with open(path, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
            for pattern in SECRET_PATTERNS:
                match = pattern.search(text)
                if match:
                    self.assertIn(
                        rel, SECRET_ALLOWLIST,
                        "secret-shaped value in %s: %s"
                        % (rel, match.group(0)[:20]))

    def test_required_docs_exist(self):
        for name in ("README.md", "CHANGELOG.md", "LICENSE",
                     ".gitignore"):
            self.assertTrue(os.path.exists(os.path.join(TREE, name)),
                            name)
        with open(os.path.join(TREE, ".gitignore"),
                  encoding="utf-8") as fh:
            ignored = fh.read()
        for entry in (".env", "__pycache__", "*.pyc", ".venv",
                      "*.zip"):
            self.assertIn(entry, ignored)


if __name__ == "__main__":
    unittest.main()
