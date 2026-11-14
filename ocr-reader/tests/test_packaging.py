"""Packaging: bash-clean scripts, .desktop files that survive GLib,
zip exec bits, CLI symlink resolution, SVG icon, no binaries,
no em-dashes in packaging text, and the thin-viewer import ban
(gui.py must not import the OCR machinery)."""

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

SHELL_SCRIPTS = ("install.sh", "run.sh", "ocr-reader",
                 "uninstall.sh", "run_tests.sh")
EXEC_IN_ZIP = {"install.sh", "run.sh", "ocr-reader",
               "ocr-read", "ocr-clean", "ocrreader-cli",
               "uninstall.sh", "run_tests.sh", "build_zip.py",
               "render_icons.py"}

# Files this packaging test owns: Worker A owns the engine, the
# CLI, and the chain wrappers, so sweeps that would fail on their
# files stay scoped to these. The zip mode check is the exception:
# every script in the zip needs its exec bit, whoever owns it.
PACKAGING_FILES = (
    "install.sh", "run.sh", "ocr-reader",
    "uninstall.sh", "build_zip.py", "render_icons.py",
    "ocrreader/gui.py", "ocrreader/gui_main.py",
    "Install OCR Reader.desktop",
    "ocr-reader.desktop",
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
    "assets/ocr.svg",
)

# Worker A's chain wrappers: when they exist in the tree they must
# be in the zip with their exec bit; when they do not exist yet
# (Worker A still building) the zip test must not fail on their
# absence.
CHAIN_WRAPPERS = ("ocr-read", "ocr-clean", "ocrreader-cli")

# The fixed S6 installer Exec line, verbatim from the template
# (linux-release-packaging/references/desktop-entry-template.desktop).
# The empty-%k fallback uses os.getcwd() DIRECTLY: dirname() on it
# would go up one level and miss install.sh.
EXPECTED_INSTALLER_EXEC = (
    'Exec=python3 -c "import os, sys, subprocess; '
    "a = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else ''; "
    "d = os.path.dirname(a) if a else os.getcwd(); "
    "subprocess.call(['bash', os.path.join(d, 'install.sh')])\" %k")

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
    assets/ocr.png and assets/ocr-<size>.png. These are the
    only binaries the tree may ever hold, and only in a Release
    unzip or an installed copy - never in the pushed source."""
    if not rel.startswith("assets" + os.sep):
        return False
    name = os.path.basename(rel)
    if name == "ocr.png":
        return True
    if name.startswith("ocr-") and name.endswith(".png"):
        size = name[len("ocr-"):-len(".png")]
        return size.isdigit()
    return False


def render_env():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    qt_lib = os.path.expanduser(
        "~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu")
    if os.path.isdir(qt_lib):
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            qt_lib + os.pathsep + old if old else qt_lib)
        env["__EGL_VENDOR_LIBRARY_DIRS"] = os.path.expanduser(
            "~/workspace/qt-libs/root/usr/share/glvnd/egl_vendor.d")
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

    def test_installer_checks_tesseract_first(self):
        # The FIRST check: tesseract missing means plain install
        # instructions with the exact command, then stop. No
        # self-heal for tesseract, and no pdftoppm check (PDF is
        # best-effort; the CLI errors plainly at runtime).
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("command -v tesseract", text)
        self.assertIn("sudo apt install tesseract-ocr", text)
        self.assertNotIn("pdftoppm", text)
        # The tesseract check comes before the venv is created.
        self.assertLess(text.index("command -v tesseract"),
                        text.index("python3 -m venv"))

    def test_installer_installs_only_pyside6(self):
        # The product needs NO pip deps beyond the interface
        # toolkit: the engine shells out to the tesseract binary.
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("PySide6-Essentials", text)
        self.assertIn("PySide6-Addons", text)
        for dep in ("Pillow", "pytesseract", "pdf2image",
                    "PyMuPDF", "fitz"):
            self.assertNotIn(dep, text, dep)

    def test_installer_reports_download_failure(self):
        # A failed download must say so plainly, never fail
        # silently.
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("the download failed 3 times", text)

    def test_run_sh_opens_gui_main_without_args(self):
        with open(os.path.join(TREE, "run.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("ocrreader.gui_main", text)
        self.assertIn("-m ocrreader", text)


class GuiImportBanTests(unittest.TestCase):
    """The thin viewer must not import the OCR machinery: no
    engine, no clean, no CLI, and no image or OCR library in the
    viewer process. The check parses real import statements
    (ast), not substrings, so a docstring that names the banned
    modules does not trip it."""

    BANNED = {"ocrreader.engine", "ocrreader.clean", "ocrreader.cli",
              "PIL", "pytesseract"}

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
                    # ocrreader package (gui.py lives in
                    # ocrreader/).
                    found.add("ocrreader." + node.module)
                else:
                    found.add(node.module)
        return found

    def test_gui_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "ocrreader", "gui.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_main_py_import_ban(self):
        imports = self._imports_of(
            os.path.join(TREE, "ocrreader", "gui_main.py"))
        banned = imports & self.BANNED
        self.assertEqual(banned, set(),
                         "gui_main.py imports banned modules: %s"
                         % sorted(banned))

    def test_gui_py_does_import_settings_and_logsetup(self):
        imports = self._imports_of(
            os.path.join(TREE, "ocrreader", "gui.py"))
        self.assertIn("ocrreader.settings", imports)
        self.assertIn("ocrreader.logsetup", imports)


class DesktopFileTests(unittest.TestCase):
    NAMES = ("Install OCR Reader.desktop",
             "ocr-reader.desktop")

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
        text = self._read("Install OCR Reader.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=Install OCR Reader", text)
        self.assertIn("Terminal=false", text)
        exec_line = self._exec_line(text)
        self.assertIn("install.sh", exec_line)
        self.assertIn("%k", exec_line)
        # GLib rejects nested escaped quotes in Exec outright.
        self.assertNotIn('\\"', exec_line)

    def test_installer_exec_matches_fixed_template(self):
        # The Exec line must be identical to the fixed S6
        # template's, verbatim: %k as a separate argv token,
        # dirname in Python, and the empty-%k fallback uses the
        # working directory DIRECTLY.
        exec_line = self._exec_line(
            self._read("Install OCR Reader.desktop"))
        self.assertEqual(exec_line, EXPECTED_INSTALLER_EXEC)
        self.assertNotIn("os.path.dirname(os.getcwd())",
                         exec_line)
        # And against the template file itself, when it is there
        # to diff against (it lives outside this tree).
        template = os.path.join(
            os.path.dirname(os.path.dirname(TREE)),
            "bnb-skills", "linux-release-packaging", "references",
            "desktop-entry-template.desktop")
        if os.path.exists(template):
            with open(template, encoding="utf-8") as fh:
                template_exec = self._exec_line(fh.read())
            self.assertEqual(exec_line, template_exec)

    def test_app_desktop_template_structural(self):
        text = self._read("ocr-reader.desktop")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=OCR Reader", text)
        self.assertIn("Terminal=false", text)
        self.assertIn("StartupWMClass=OCR Reader", text)
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
        self.assertIn("Icon=$DIR/assets/ocr.png", text)
        self.assertNotIn('Icon="$DIR/assets/ocr.png"', text)

    def test_installer_links_gui_launcher_and_clis(self):
        with open(os.path.join(TREE, "install.sh"),
                  encoding="utf-8") as fh:
            text = fh.read()
        for link in ("ocr-reader", "ocrreader-cli",
                     "ocr-read", "ocr-clean"):
            self.assertIn(link, text, link)


class ZipTests(unittest.TestCase):
    def _copy_tree(self, tmp):
        copy = os.path.join(tmp, "ocr-reader")
        shutil.copytree(TREE, copy, ignore=shutil.ignore_patterns(
            "__pycache__", ".venv", "*.zip", ".git", "logs"))
        return copy

    def _assert_modes(self, zpath, copy):
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            # No duplicate entries (a rendered icon collected
            # from the tree AND rendered fresh would double up).
            self.assertEqual(len(names), len(set(names)),
                             "duplicate zip entries")
            self.assertIn("install.sh", names)
            self.assertIn("ocrreader/gui.py", names)
            self.assertIn("ocrreader/gui_main.py", names)
            self.assertIn("ocr-reader", names)
            # Worker A's wrappers: in the zip when they exist in
            # the tree copy, skipped when they do not exist yet.
            for wrapper in CHAIN_WRAPPERS:
                if os.path.exists(os.path.join(copy, wrapper)):
                    self.assertIn(wrapper, names, wrapper)
            self.assertIn("assets/ocr.svg", names)
            # Rendered PNGs ship in the zip, not the tree.
            self.assertIn("assets/ocr-16.png", names)
            self.assertIn("assets/ocr-256.png", names)
            self.assertIn("assets/ocr.png", names)
            self.assertNotIn("BUILD_REPORT.md", names)
            self.assertNotIn("install.log", names)
            for name in names:
                self.assertFalse(name.endswith(".pyc"), name)
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
            self._assert_modes(out, copy)
            # Test-extract with the unzip CLI: Python's zipfile
            # never restores stored modes, but unzip does - and
            # the GUI extractors on his PC behave like unzip.
            extract = os.path.join(tmp, "extracted")
            proc = subprocess.run(
                ["unzip", "-q", "-o", out, "-d", extract],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            present = ["install.sh", "run.sh", "ocr-reader"]
            for wrapper in CHAIN_WRAPPERS:
                if os.path.exists(os.path.join(copy, wrapper)):
                    present.append(wrapper)
            for name in present:
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
                tmp, "ocr-reader-v0.1.0.zip")
            self.assertTrue(os.path.exists(expected), expected)
            self.assertEqual(
                [f for f in os.listdir(copy)
                 if f.endswith(".zip")], [])

    def test_tree_has_no_png(self):
        # The source tree ships no PNGs - but a fresh unzip of the
        # Release zip (and an installed copy) legitimately carries
        # the rendered icons at assets/ocr*.png, so those exact
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
            link = os.path.join(bindir, "ocr-reader")
            os.symlink(os.path.join(TREE, "ocr-reader"),
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


class IconTests(unittest.TestCase):
    def test_icon_svg_parses_as_xml(self):
        path = os.path.join(TREE, "assets", "ocr.svg")
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
                                    "ocr-%d.png" % size)
                self.assertTrue(os.path.exists(path), path)
                with open(path, "rb") as fh:
                    self.assertEqual(
                        fh.read(8), b"\x89PNG\r\n\x1a\n", path)
            self.assertTrue(os.path.exists(
                os.path.join(out_dir, "ocr.png")))


class TreeHygieneTests(unittest.TestCase):
    def test_no_binary_files_in_tree(self):
        # Snapshot pushes cannot carry binaries: every file in
        # this folder must decode as UTF-8 text. The one exception
        # is the rendered icon set (assets/ocr*.png), which a
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
                     "run.sh", "uninstall.sh", "ocr-reader",
                     "Install OCR Reader.desktop",
                     "ocr-reader.desktop",
                     "ocrreader/gui.py", "ocrreader/gui_main.py"):
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
