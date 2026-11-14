"""Packaging: bash-clean scripts, .desktop files that survive GLib,
zip exec bits, CLI symlink resolution, SVG icon, no binaries,
no em-dashes in packaging text."""

import ast
import configparser
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHELL_SCRIPTS = ("install.sh", "run.sh", "scrubber-cli",
                 "safe-share-scrub", "safe-share-verify",
                 "uninstall.sh")
EXEC_IN_ZIP = {"install.sh", "run.sh", "scrubber-cli",
               "safe-share-scrub", "safe-share-verify",
               "uninstall.sh", "run_tests.sh", "build_zip.py",
               "render_icons.py"}

# Files this packaging test owns: the core builder owns scrubber/
# and the other tests, so hygiene sweeps that would fail on their
# files stay scoped to these.
PACKAGING_FILES = (
    "install.sh", "run.sh", "scrubber-cli",
    "safe-share-scrub", "safe-share-verify", "uninstall.sh",
    "build_zip.py", "render_icons.py",
    "Install Safe Share Scrubber.desktop",
    "safe-share-scrubber.desktop",
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
    "assets/scrubber.svg",
)

SKIP_DIRS = {"__pycache__", ".venv", ".git", "logs"}


def tree_files():
    found = []
    for root, dirs, files in os.walk(TREE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            found.append(os.path.join(root, name))
    return found


def _is_rendered_icon(rel):
    """True for exactly the icon files render_icons.py produces:
    assets/scrubber.png and assets/scrubber-<size>.png. These are
    the only binaries the tree may ever hold, and only in a Release
    unzip or an installed copy — never in the pushed source."""
    if not rel.startswith("assets" + os.sep):
        return False
    name = os.path.basename(rel)
    if name == "scrubber.png":
        return True
    if name.startswith("scrubber-") and name.endswith(".png"):
        size = name[len("scrubber-"):-len(".png")]
        return size.isdigit()
    return False


def render_env():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


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
        import re
        pattern = re.compile(r"(^|\s)sh (install|run)\.sh")
        for name in ("install.sh", "run.sh", "README.md"):
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(pattern.search(text), name)


class DesktopFileTests(unittest.TestCase):
    NAMES = ("Install Safe Share Scrubber.desktop",
             "safe-share-scrubber.desktop")

    def _read(self, name):
        with open(os.path.join(TREE, name),
                  encoding="utf-8") as fh:
            return fh.read()

    def _exec_line(self, text):
        lines = [ln for ln in text.splitlines()
                 if ln.startswith("Exec=")]
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_installer_desktop_structural(self):
        text = self._read("Install Safe Share Scrubber.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Install Safe Share Scrubber", text)
        self.assertIn("Terminal=false", text)
        exec_line = self._exec_line(text)
        self.assertIn("install.sh", exec_line)
        self.assertIn("%k", exec_line)
        # GLib rejects nested escaped quotes in Exec outright.
        self.assertNotIn('\\"', exec_line)

    def test_app_desktop_template_structural(self):
        text = self._read("safe-share-scrubber.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Safe Share Scrubber", text)
        self.assertIn("Terminal=false", text)
        self.assertIn("StartupWMClass=Safe Share Scrubber", text)
        exec_line = self._exec_line(text)
        self.assertNotIn('\\"', exec_line)
        icon_line = [ln for ln in text.splitlines()
                     if ln.startswith("Icon=")][0]
        # Icon= must NOT be quoted: GLib takes it literally.
        self.assertFalse(icon_line.startswith('Icon="'),
                         icon_line)

    def test_desktop_files_parse(self):
        validator = shutil.which("desktop-file-validate")
        if validator is not None:
            for name in self.NAMES:
                proc = subprocess.run(
                    [validator, os.path.join(TREE, name)],
                    capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0,
                                 "%s: %s" % (name, proc.stdout))
            return
        # No validator installed: parse as INI instead (desktop
        # files are INI-shaped) and assert the Exec line has no
        # nested escaped quote, which is what breaks GLib.
        for name in self.NAMES:
            parser = configparser.RawConfigParser()
            parser.read(os.path.join(TREE, name),
                        encoding="utf-8")
            self.assertTrue(parser.has_section("Desktop Entry"),
                            name)
            exec_line = parser.get("Desktop Entry", "Exec")
            self.assertNotIn('\\"', exec_line, name)
            self.assertTrue(parser.get("Desktop Entry", "Name"),
                            name)


class ZipTests(unittest.TestCase):
    def _copy_tree(self, tmp):
        copy = os.path.join(tmp, "safe-share-scrubber")
        shutil.copytree(TREE, copy, ignore=shutil.ignore_patterns(
            "__pycache__", ".venv", "*.zip", ".git", "logs"))
        return copy

    def _assert_modes(self, zpath):
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            self.assertIn("install.sh", names)
            self.assertIn("assets/scrubber.svg", names)
            # Rendered PNGs ship in the zip, not the tree.
            self.assertIn("assets/scrubber-16.png", names)
            self.assertIn("assets/scrubber-256.png", names)
            self.assertIn("assets/scrubber.png", names)
            self.assertNotIn("BUILD_REPORT.md", names)
            for info in zf.infolist():
                # The full upper 16 bits are the stored mode,
                # file-type bits included - do not mask them off.
                mode = info.external_attr >> 16
                base = os.path.basename(info.filename)
                if base in EXEC_IN_ZIP:
                    self.assertEqual(mode, 0o100755,
                                     info.filename)
                elif not info.is_dir():
                    self.assertEqual(mode, 0o100644,
                                     info.filename)
        return names

    def test_build_zip_modes_and_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_tree(tmp)
            out = os.path.join(tmp, "out.zip")
            proc = subprocess.run(
                [sys.executable, "build_zip.py",
                 "--out", out],
                cwd=copy, capture_output=True, text=True,
                timeout=300, env=render_env())
            self.assertEqual(proc.returncode, 0,
                             proc.stdout + proc.stderr)
            self.assertTrue(os.path.exists(out))
            # The zip was built to a temp dir: none left in the
            # folder, and none in the copied tree either.
            self.assertEqual(
                [f for f in os.listdir(copy)
                 if f.endswith(".zip")], [])
            self._assert_modes(out)
            # Test-extract with the unzip CLI: Python's zipfile
            # never restores stored modes, but unzip does - and
            # the GUI extractors on his PC behave like unzip.
            extract = os.path.join(tmp, "extracted")
            proc = subprocess.run(
                ["unzip", "-q", "-o", out, "-d", extract],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.access(
                os.path.join(extract, "install.sh"), os.X_OK))
            self.assertTrue(os.access(
                os.path.join(extract, "run.sh"), os.X_OK))
            self.assertTrue(os.access(
                os.path.join(extract, "scrubber-cli"), os.X_OK))
            self.assertTrue(os.access(
                os.path.join(extract, "safe-share-scrub"),
                os.X_OK))
            self.assertTrue(os.access(
                os.path.join(extract, "safe-share-verify"),
                os.X_OK))

    def test_default_output_lands_outside_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_tree(tmp)
            proc = subprocess.run(
                [sys.executable, "build_zip.py"],
                cwd=copy, capture_output=True, text=True,
                timeout=300, env=render_env())
            self.assertEqual(proc.returncode, 0,
                             proc.stdout + proc.stderr)
            expected = os.path.join(
                tmp, "safe-share-scrubber-v0.2.0.zip")
            self.assertTrue(os.path.exists(expected), expected)
            self.assertEqual(
                [f for f in os.listdir(copy)
                 if f.endswith(".zip")], [])

    def test_tree_has_no_png(self):
        # The source tree ships no PNGs — but a fresh unzip of the
        # Release zip (and an installed copy) legitimately carries
        # the rendered icons at assets/scrubber*.png, so those exact
        # names are allowed and any other PNG still fails.
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
            if _is_rendered_icon(rel):
                continue
            self.assertFalse(path.endswith(".png"), path)


class CliTests(unittest.TestCase):
    WRAPPERS = (("scrubber-cli", "safe-share-scrubber"),
                ("safe-share-scrub", "safe-share-scrub"),
                ("safe-share-verify", "safe-share-verify"))

    def test_wrappers_resolve_installed_symlinks(self):
        # Regression: the installed commands are symlinks in
        # ~/.local/bin; each wrapper must resolve its link and
        # find the app folder, or the import dies with
        # ModuleNotFoundError. Run through bash: the clone
        # simulation has every file 100644, and bash still proves
        # the resolution logic.
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            for wrapper, link_name in self.WRAPPERS:
                link = os.path.join(bindir, link_name)
                os.symlink(os.path.join(TREE, wrapper), link)
                proc = subprocess.run(
                    ["bash", link, "--help"], cwd=tmp,
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0,
                                 "%s: %s" % (link_name,
                                             proc.stdout
                                             + proc.stderr))
                self.assertNotIn("ModuleNotFoundError",
                                 proc.stderr)
                self.assertTrue(proc.stdout.strip(), link_name)

    def test_install_and_uninstall_cover_all_three_cli_symlinks(
            self):
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            install = fh.read()
        with open(os.path.join(TREE, "uninstall.sh"),
                  encoding="utf-8") as fh:
            uninstall = fh.read()
        for wrapper, link_name in self.WRAPPERS:
            self.assertIn(
                'ln -sf "$DIR/%s" "$HOME/.local/bin/%s"'
                % (wrapper, link_name), install)
            self.assertIn(
                'rm -f "$HOME/.local/bin/%s"' % link_name,
                uninstall)


class GuiImportBanTests(unittest.TestCase):
    # The GUI is a thin viewer: it runs the CLI as a subprocess
    # and must never import the engine, the report builder, the
    # CLI, or the verify scanner. Follows the T30 pattern: parse
    # gui.py with ast and check the real imports.
    BANNED = {"scrubber.core", "scrubber.report", "scrubber.cli",
              "scrubber.verify"}

    def _imports_of(self, path):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                if node.level:
                    # A relative import: resolve against the
                    # scrubber package (gui.py lives in scrubber/).
                    found.add("scrubber." + node.module)
                else:
                    found.add(node.module)
        return found

    def test_gui_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "scrubber", "gui.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_py_does_import_logsetup_and_settings(self):
        imports = self._imports_of(
            os.path.join(TREE, "scrubber", "gui.py"))
        self.assertIn("scrubber.logsetup", imports)
        self.assertIn("scrubber.settings", imports)


class TreeHygieneTests(unittest.TestCase):
    def test_icon_svg_parses_as_xml(self):
        path = os.path.join(TREE, "assets", "scrubber.svg")
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.get("width"), "256")
        self.assertEqual(root.get("height"), "256")

    def test_no_binary_files_in_tree(self):
        # Snapshot pushes cannot carry binaries: every file in
        # this folder must decode as UTF-8 text. The one exception
        # is the rendered icon set (assets/scrubber*.png), which a
        # Release zip and an installed copy legitimately carry —
        # those exact names are allowed, any other binary fails.
        binary_exts = {".png", ".jpg", ".jpeg", ".pyc", ".so",
                       ".ico", ".ttf", ".zip"}
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
            if _is_rendered_icon(rel):
                continue
            ext = os.path.splitext(path)[1].lower()
            self.assertNotIn(ext, binary_exts, rel)
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                self.fail("not UTF-8 text: %s" % rel)

    def test_no_em_dash_in_packaging_text(self):
        # U33: no em-dashes in visible text. The GUI sweep lives
        # in the core builder's test_gui.py; this covers the
        # README and the other packaging strings the user sees.
        for name in ("README.md", "CHANGELOG.md", "install.sh",
                     "run.sh", "uninstall.sh", "scrubber-cli",
                     "safe-share-scrub", "safe-share-verify",
                     "Install Safe Share Scrubber.desktop",
                     "safe-share-scrubber.desktop"):
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("\u2014", text, name)

    def test_no_todo_or_fixme_in_packaging_files(self):
        # The markers are built from parts so this test file does
        # not trip its own check.
        markers = ("TO" + "DO", "FIX" + "ME")
        for name in PACKAGING_FILES:
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
            for marker in markers:
                self.assertNotIn(marker, text, name)

    def test_required_docs_exist(self):
        for name in ("README.md", "CHANGELOG.md", "LICENSE",
                     ".gitignore"):
            self.assertTrue(os.path.exists(os.path.join(TREE, name)),
                            name)
        with open(os.path.join(TREE, ".gitignore"),
                  encoding="utf-8") as fh:
            ignored = fh.read()
        for entry in (".env", "providers.json", "__pycache__",
                      "*.pyc", ".venv", "*.zip", "logs",
                      "assets/*.png"):
            self.assertIn(entry, ignored)


if __name__ == "__main__":
    unittest.main()
