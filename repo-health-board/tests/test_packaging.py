"""Packaging: bash-clean scripts, .desktop files that survive GLib,
zip exec bits, CLI symlink resolution, SVG icon, no binaries,
no em-dashes in packaging text, and the thin-viewer import ban
(gui.py must not import the fetch/flag machinery)."""

import ast
import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHELL_SCRIPTS = ("install.sh", "run.sh", "repo-health-board-cli",
                 "uninstall.sh", "run_tests.sh", "board-fetch",
                 "board-flag")
EXEC_IN_ZIP = {"install.sh", "run.sh", "repo-health-board-cli",
               "uninstall.sh", "run_tests.sh", "build_zip.py",
               "render_icons.py", "board-fetch", "board-flag"}

# Files this packaging test owns: the core builder owns board/ and
# the other tests, so hygiene sweeps that would fail on their
# files stay scoped to these.
PACKAGING_FILES = (
    "install.sh", "run.sh", "repo-health-board-cli",
    "uninstall.sh", "build_zip.py", "render_icons.py",
    "board/gui.py", "board/gui_main.py",
    "Install Repo Health Board.desktop",
    "repo-health-board.desktop",
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
    "assets/board.svg",
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
    assets/board.png and assets/board-<size>.png. These are the
    only binaries the tree may ever hold, and only in a Release
    unzip or an installed copy - never in the pushed source."""
    if not rel.startswith("assets" + os.sep):
        return False
    name = os.path.basename(rel)
    if name == "board.png":
        return True
    if name.startswith("board-") and name.endswith(".png"):
        size = name[len("board-"):-len(".png")]
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
        pattern = re.compile(r"(^|\s)sh (install|run)\.sh")
        for name in ("install.sh", "run.sh", "README.md"):
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(pattern.search(text), name)

    def test_installer_has_headless_flag(self):
        # The fresh-unzip install test drives install.sh with
        # --headless; the flag must exist and be honored.
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"--headless"', text)

    def test_run_sh_opens_gui_main_without_args(self):
        with open(os.path.join(TREE, "run.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("board.gui_main", text)
        self.assertIn("-m board", text)


class GuiImportBanTests(unittest.TestCase):
    """The thin viewer must not import the fetch/flag machinery:
    no fetching and no flagging in the viewer process. The check
    parses real import statements (ast), not substrings, so a
    docstring that names the banned modules does not trip it."""

    BANNED = {"board.api", "board.flags", "board.refresh",
              "board.cache", "board.export", "board.cli",
              "board.fetch", "board.flag"}

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
                    # board package (gui.py lives in board/).
                    found.add("board." + node.module)
                else:
                    found.add(node.module)
        return found

    def test_gui_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "board", "gui.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_main_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "board", "gui_main.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui_main.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_py_does_import_settings_and_debug_log(self):
        imports = self._imports_of(
            os.path.join(TREE, "board", "gui.py"))
        self.assertIn("board.settings", imports)
        self.assertIn("board.debug_log", imports)


class DesktopFileTests(unittest.TestCase):
    NAMES = ("Install Repo Health Board.desktop",
             "repo-health-board.desktop")

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
        text = self._read("Install Repo Health Board.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Install Repo Health Board", text)
        self.assertIn("Terminal=false", text)
        exec_line = self._exec_line(text)
        self.assertIn("install.sh", exec_line)
        self.assertIn("%k", exec_line)
        # GLib rejects nested escaped quotes in Exec outright.
        self.assertNotIn('\\"', exec_line)

    def test_installer_exec_follows_fixed_template(self):
        # The fixed template form (2026-11-14): %k as a separate
        # argv token, dirname in Python, and the empty-%k
        # fallback uses the working directory DIRECTLY - the old
        # form ran dirname() on it and missed install.sh by one
        # level.
        exec_line = self._exec_line(
            self._read("Install Repo Health Board.desktop"))
        self.assertTrue(exec_line.startswith(
            'Exec=python3 -c "import os, sys, subprocess;'),
            exec_line)
        self.assertIn(
            "d = os.path.dirname(a) if a else os.getcwd()",
            exec_line)
        self.assertNotIn("os.path.dirname(os.getcwd())",
                         exec_line)
        self.assertIn(
            "subprocess.call(['bash', os.path.join(d, "
            "'install.sh')])",
            exec_line)
        self.assertTrue(exec_line.endswith('" %k'), exec_line)

    def test_app_desktop_template_structural(self):
        text = self._read("repo-health-board.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Repo Health Board", text)
        self.assertIn("Terminal=false", text)
        self.assertIn("StartupWMClass=Repo Health Board", text)
        exec_line = self._exec_line(text)
        self.assertNotIn('\\"', exec_line)
        # The template's Exec is quoted; the installer writes
        # the real absolute path in the same quoted form.
        self.assertTrue(exec_line.startswith('Exec="'),
                        exec_line)
        self.assertIn("run.sh", exec_line)
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

    def test_installer_writes_quoted_exec_unquoted_icon(self):
        # The .desktop the installer generates must quote Exec
        # and leave Icon unquoted (STELLA v0.3.1 lesson: a quoted
        # Icon breaks the menu icon).
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('Exec="$DIR/run.sh"', text)
        self.assertIn("Icon=$DIR/assets/board.png", text)
        self.assertNotIn('Icon="$DIR/assets/board.png"', text)


class ZipTests(unittest.TestCase):
    def _copy_tree(self, tmp):
        copy = os.path.join(tmp, "repo-health-board")
        shutil.copytree(TREE, copy, ignore=shutil.ignore_patterns(
            "__pycache__", ".venv", "*.zip", ".git", "logs"))
        return copy

    def _assert_modes(self, zpath):
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            # No duplicate entries (a rendered icon collected
            # from the tree AND rendered fresh would double up).
            self.assertEqual(len(names), len(set(names)),
                             "duplicate zip entries")
            self.assertIn("install.sh", names)
            self.assertIn("board/gui.py", names)
            self.assertIn("board/gui_main.py", names)
            self.assertIn("board-fetch", names)
            self.assertIn("board-flag", names)
            self.assertIn("assets/board.svg", names)
            # Rendered PNGs ship in the zip, not the tree.
            self.assertIn("assets/board-16.png", names)
            self.assertIn("assets/board-256.png", names)
            self.assertIn("assets/board.png", names)
            self.assertNotIn("BUILD_REPORT.md", names)
            self.assertNotIn("install.log", names)
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
            for name in ("install.sh", "run.sh",
                         "repo-health-board-cli", "board-fetch",
                         "board-flag"):
                self.assertTrue(os.access(
                    os.path.join(extract, name), os.X_OK), name)

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
                tmp, "repo-health-board-v0.1.0.zip")
            self.assertTrue(os.path.exists(expected), expected)
            self.assertEqual(
                [f for f in os.listdir(copy)
                 if f.endswith(".zip")], [])

    def test_tree_has_no_png(self):
        # The source tree ships no PNGs - but a fresh unzip of the
        # Release zip (and an installed copy) legitimately carries
        # the rendered icons at assets/board*.png, so those exact
        # names are allowed and any other PNG still fails.
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
            if _is_rendered_icon(rel):
                continue
            self.assertFalse(path.endswith(".png"), path)


class CliTests(unittest.TestCase):
    def test_wrapper_resolves_installed_symlink(self):
        # Regression: the installed command is a symlink in
        # ~/.local/bin; the wrapper must resolve it and find the
        # app folder, or the import dies with ModuleNotFoundError.
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            link = os.path.join(bindir, "repo-health-board")
            os.symlink(os.path.join(TREE,
                                    "repo-health-board-cli"),
                       link)
            # Invoked through bash, not executed directly: a
            # fresh clone stores every file 100644, so the
            # suite must not depend on the stored exec bit.
            proc = subprocess.run(
                ["bash", link, "--help"], cwd=tmp,
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0,
                             proc.stdout + proc.stderr)
            self.assertNotIn("ModuleNotFoundError", proc.stderr)
            self.assertTrue(proc.stdout.strip())

    def test_chain_wrappers_resolve_installed_symlink(self):
        # Same regression for the chain pieces: board-fetch and
        # board-flag run through their installed symlinks.
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            for name in ("board-fetch", "board-flag"):
                link = os.path.join(bindir, name)
                os.symlink(os.path.join(TREE, name), link)
                # Through bash, not executed directly (see the
                # clone note above).
                proc = subprocess.run(
                    ["bash", link, "--help"], cwd=tmp,
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0,
                                 "%s: %s" % (name,
                                             proc.stdout
                                             + proc.stderr))
                self.assertNotIn("ModuleNotFoundError",
                                 proc.stderr)


class IconTests(unittest.TestCase):
    def test_icon_svg_parses_as_xml(self):
        path = os.path.join(TREE, "assets", "board.svg")
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.get("width"), "256")
        self.assertEqual(root.get("height"), "256")

    def test_render_icons_in_subprocess(self):
        # The render runs in its own process, never inside the
        # test process: a render crash fails the render, not the
        # suite.
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "icons")
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(TREE, "render_icons.py"),
                 "--out-dir", out_dir],
                capture_output=True, text=True, timeout=120,
                env=render_env())
            self.assertEqual(proc.returncode, 0,
                             proc.stdout + proc.stderr)
            for size in (16, 32, 48, 64, 128, 256):
                path = os.path.join(out_dir,
                                    "board-%d.png" % size)
                self.assertTrue(os.path.exists(path), path)
                with open(path, "rb") as fh:
                    self.assertEqual(
                        fh.read(8), b"\x89PNG\r\n\x1a\n", path)
            self.assertTrue(os.path.exists(
                os.path.join(out_dir, "board.png")))


class TreeHygieneTests(unittest.TestCase):
    def test_no_binary_files_in_tree(self):
        # Snapshot pushes cannot carry binaries: every file in
        # this folder must decode as UTF-8 text. The one exception
        # is the rendered icon set (assets/board*.png), which a
        # Release zip and an installed copy legitimately carry -
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
        # in test_gui.py; this covers the source files whose
        # strings the user sees.
        for name in ("README.md", "CHANGELOG.md", "install.sh",
                     "run.sh", "uninstall.sh",
                     "repo-health-board-cli", "board-fetch",
                     "board-flag",
                     "Install Repo Health Board.desktop",
                     "repo-health-board.desktop",
                     "board/gui.py", "board/gui_main.py"):
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
