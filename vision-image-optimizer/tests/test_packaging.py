"""Packaging: bash-clean scripts, .desktop files that survive GLib,
zip exec bits, CLI symlink resolution, SVG icon, no binaries, no
leftover markers, no secrets, and the thin-viewer import ban
(gui.py must not import the shrink/describe/cache machinery)."""

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
ZIP_NAME = "vision-image-optimizer-v0.2.0.zip"

SHELL_SCRIPTS = ("install.sh", "run.sh", "optimizer-cli",
                 "uninstall.sh", "run_tests.sh", "vision-shrink",
                 "vision-describe")
EXEC_IN_ZIP = {"install.sh", "run.sh", "optimizer-cli",
               "uninstall.sh", "run_tests.sh", "build_zip.py",
               "render_icons.py", "vision-shrink", "vision-describe"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"password\s*=\s*[\"'][^\"']{4,}[\"']"),
    re.compile(r"api[_-]?key\s*=\s*[\"'][^\"']{4,}[\"']"),
]
# The scrub test's deliberate fakes live here and only here.
SECRET_ALLOWLIST = {os.path.join("tests", "test_debug_log.py")}

# Files this packaging test owns for the em-dash sweep: the engine
# builder owns the optimizer modules, the chain wrappers, and
# optimizer-cli, so a sweep over their files would fail this test
# on their content. (optimizer-cli carries one em-dash in a header
# comment; it is not visible text, and the file is not ours to edit.)
EM_DASH_FILES = (
    "install.sh", "run.sh", "uninstall.sh",
    "build_zip.py", "render_icons.py",
    "optimizer/gui.py",
    "Install Vision Image Optimizer.desktop",
    "vision-image-optimizer.desktop",
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
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
    assets/vision.png and assets/vision-<size>.png. These are the
    only binaries the tree may ever hold, and only in a Release
    unzip or an installed copy - never in the pushed source."""
    if not rel.startswith("assets" + os.sep):
        return False
    name = os.path.basename(rel)
    if name == "vision.png":
        return True
    if name.startswith("vision-") and name.endswith(".png"):
        size = name[len("vision-"):-len(".png")]
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

    def test_installer_links_chain_commands(self):
        # The chain commands land on PATH next to the combined CLI.
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(
            'ln -sf "$DIR/vision-shrink" '
            '"$HOME/.local/bin/vision-shrink"', text)
        self.assertIn(
            'ln -sf "$DIR/vision-describe" '
            '"$HOME/.local/bin/vision-describe"', text)

    def test_uninstaller_removes_chain_commands(self):
        with open(os.path.join(TREE, "uninstall.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('rm -f "$HOME/.local/bin/vision-shrink"',
                      text)
        self.assertIn('rm -f "$HOME/.local/bin/vision-describe"',
                      text)

    def test_run_sh_opens_gui_unchanged(self):
        # run.sh still launches the window via the package entry
        # point; the thin viewer changed what the GUI does, not
        # how it starts.
        with open(os.path.join(TREE, "run.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("-m optimizer", text)


class GuiImportBanTests(unittest.TestCase):
    """The thin viewer must not import the shrink/describe/cache
    machinery: no shrinking, no describing, and no image decoding
    in the viewer process. The check parses real import statements
    (ast), not substrings, so a docstring that names the banned
    modules does not trip it."""

    BANNED = {"optimizer.shrink", "optimizer.describe",
              "optimizer.cache", "optimizer.ollama",
              "optimizer.cli", "PIL", "urllib"}

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
                    # optimizer package (gui.py lives in
                    # optimizer/).
                    found.add("optimizer." + node.module)
                else:
                    found.add(node.module)
        return found

    def test_gui_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "optimizer", "gui.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_py_does_import_tokens_settings_logsetup(self):
        imports = self._imports_of(
            os.path.join(TREE, "optimizer", "gui.py"))
        self.assertIn("optimizer.tokens", imports)
        self.assertIn("optimizer.settings", imports)
        self.assertIn("optimizer.logsetup", imports)


class DesktopFileTests(unittest.TestCase):
    NAMES = ("Install Vision Image Optimizer.desktop",
             "vision-image-optimizer.desktop")

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
        text = self._read("Install Vision Image Optimizer.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Install Vision Image Optimizer", text)
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
            self._read("Install Vision Image Optimizer.desktop"))
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

    def test_installer_exec_matches_s6_template(self):
        # Exact diff against the S6 template's Exec line, not an
        # eyeball. Skipped outside the workspace (a shipped tree
        # has no S6 folder next to it); the structural test above
        # still pins the form there.
        template = os.path.join(
            os.path.dirname(os.path.dirname(TREE)),
            "bnb-skills", "linux-release-packaging",
            "references", "desktop-entry-template.desktop")
        if not os.path.exists(template):
            self.skipTest("S6 template not present next to the tree")
        with open(template, encoding="utf-8") as fh:
            template_exec = self._exec_line(fh.read())
        mine = self._exec_line(
            self._read("Install Vision Image Optimizer.desktop"))
        self.assertEqual(mine, template_exec)

    def test_app_desktop_template_structural(self):
        text = self._read("vision-image-optimizer.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Vision Image Optimizer", text)
        self.assertIn("Terminal=false", text)
        self.assertIn("StartupWMClass=Vision Image Optimizer", text)
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
        self.assertIn("Icon=$DIR/assets/vision.png", text)
        self.assertNotIn('Icon="$DIR/assets/vision.png"', text)


class ZipTests(unittest.TestCase):
    def _copy_tree(self, tmp):
        copy = os.path.join(tmp, "vision-image-optimizer")
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
            self.assertIn("optimizer/gui.py", names)
            self.assertIn("optimizer/tokens.py", names)
            self.assertIn("optimizer/shrink.py", names)
            self.assertIn("optimizer/describe.py", names)
            self.assertIn("optimizer/logsetup.py", names)
            self.assertIn("vision-shrink", names)
            self.assertIn("vision-describe", names)
            self.assertIn("assets/vision.svg", names)
            # Rendered PNGs ship in the zip, not the tree.
            self.assertIn("assets/vision-16.png", names)
            self.assertIn("assets/vision-256.png", names)
            self.assertIn("assets/vision.png", names)
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
                         "optimizer-cli", "vision-shrink",
                         "vision-describe"):
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
            expected = os.path.join(tmp, ZIP_NAME)
            self.assertTrue(os.path.exists(expected), expected)
            self.assertEqual(
                [f for f in os.listdir(copy)
                 if f.endswith(".zip")], [])

    def test_tree_has_no_png(self):
        # The source tree ships no PNGs - but a fresh unzip of the
        # Release zip (and an installed copy) legitimately carries
        # the rendered icons at assets/vision*.png, so those exact
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
            link = os.path.join(bindir, "vision-image-optimizer")
            os.symlink(os.path.join(TREE, "optimizer-cli"), link)
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
        # Same regression for the chain pieces: vision-shrink and
        # vision-describe run through their installed symlinks.
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            for name in ("vision-shrink", "vision-describe"):
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
        path = os.path.join(TREE, "assets", "vision.svg")
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
                                    "vision-%d.png" % size)
                self.assertTrue(os.path.exists(path), path)
                with open(path, "rb") as fh:
                    self.assertEqual(
                        fh.read(8), b"\x89PNG\r\n\x1a\n", path)
            self.assertTrue(os.path.exists(
                os.path.join(out_dir, "vision.png")))


class TreeHygieneTests(unittest.TestCase):
    def test_no_binary_files_in_tree(self):
        # Snapshot pushes cannot carry binaries: every file in
        # this folder must decode as UTF-8 text, and no zip may
        # sit in the tree (build_zip.py writes outside the folder
        # now). The one exception is the rendered icon set
        # (assets/vision*.png), which a Release zip and an
        # installed copy legitimately carry - those exact names
        # are allowed, any other binary fails.
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
        # in test_gui.py; this covers the source files this test
        # owns whose strings the user sees.
        for name in EM_DASH_FILES:
            path = os.path.join(TREE, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("\u2014", text, name)

    def test_no_todo_or_fixme(self):
        # The markers are built from parts so this test file does
        # not trip its own check.
        markers = ("TO" + "DO", "FIX" + "ME")
        for path in tree_files():
            with open(path, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
            for marker in markers:
                self.assertNotIn(marker, text, path)

    def test_no_secrets_in_tree(self):
        for path in tree_files():
            rel = os.path.relpath(path, TREE)
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
                      "*.zip", "assets/*.png", "logs"):
            self.assertIn(entry, ignored)


if __name__ == "__main__":
    unittest.main()
