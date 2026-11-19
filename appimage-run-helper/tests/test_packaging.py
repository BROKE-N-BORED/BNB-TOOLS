"""Packaging tests: S6 shape, the fixed desktop template, zip
modes (scripts AND .desktop files executable), no binaries, no
em-dashes, the GUI import ban, and version consistency."""

import ast
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORGE_PY = "/home/hatch/workspace/forge-v2-testenv/bin/python"

EM_DASH_BYTES = b"\xe2\x80\x94"
MARKER_A = "TO" + "DO"
MARKER_B = "FIX" + "ME"

TEXT_SUFFIXES = {".py", ".sh", ".md", ".txt", ".svg", ".desktop",
                 ".json", ".gitignore"}
NO_SUFFIX_TEXT = {"appimage-run", "appimage-make-runnable",
                  "appimagehelper-cli", "LICENSE"}

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(ROOT))),
    "build", "bnb-skills", "linux-release-packaging",
    "references", "desktop-entry-template.desktop")


def tree_text_files():
    """User-visible text files, for the em-dash sweep. Two
    exemptions, both deliberate: appimagehelper/debug_log.py is
    the T21 layer copied UNMODIFIED (hash-pinned by
    test_debug_log.py; its em-dashes live inside T21's own
    report format, shared by every tool carrying the layer, and
    "fixing" them would break the copy rule), and tests/ holds
    the escape-sequence references the sweeps themselves need.
    The GUI's visible text is swept separately in test_gui.py.
    """
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".venv", "__pycache__", ".git",
                                    "tests")]
        for name in filenames:
            if name == "debug_log.py":
                continue
            if os.path.splitext(name)[1] in TEXT_SUFFIXES or \
                    name in NO_SUFFIX_TEXT:
                yield os.path.join(dirpath, name)


def all_text_files():
    """Every text file in the tree, tests included, for the
    leftover-marker sweep (the marker words are built from
    parts in the test files, so the sweep can cover the test
    files safely too)."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".venv", "__pycache__", ".git")]
        for name in filenames:
            if os.path.splitext(name)[1] in TEXT_SUFFIXES or \
                    name in NO_SUFFIX_TEXT:
                yield os.path.join(dirpath, name)


def exec_line(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Exec="):
                return line.rstrip("\n")
    return None


class ShellSyntaxTests(unittest.TestCase):

    def test_shell_scripts_parse(self):
        for name in ("install.sh", "uninstall.sh", "run.sh",
                     "run_tests.sh", "appimage-run",
                     "appimage-make-runnable", "appimagehelper-cli"):
            path = os.path.join(ROOT, name)
            result = subprocess.run(["bash", "-n", path],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                             "%s: %s" % (name, result.stderr))


class DesktopEntryTests(unittest.TestCase):

    def test_installer_exec_matches_fixed_template(self):
        # The S6 rule: the installer .desktop Exec must diff
        # identical to the fixed template in the S6 skill.
        self.assertTrue(os.path.isfile(TEMPLATE_PATH),
                        "fixed template missing: %s" % TEMPLATE_PATH)
        mine = exec_line(os.path.join(
            ROOT, "Install AppImage Runner.desktop"))
        fixed = exec_line(TEMPLATE_PATH)
        self.assertIsNotNone(fixed)
        self.assertEqual(mine, fixed)
        # The empty-%k fallback uses os.getcwd() DIRECTLY.
        self.assertIn("os.getcwd()", mine)
        self.assertNotIn("dirname(os.getcwd", mine)

    def test_app_launcher_has_placeholders(self):
        text = open(os.path.join(
            ROOT, "appimage-run-helper.desktop"),
            encoding="utf-8").read()
        self.assertIn("Exec=/path/to/AppImage Runner/run.sh", text)
        self.assertIn(
            "Icon=/path/to/AppImage Runner/assets/appimage.png",
            text)

    def test_installer_generates_quoted_exec_unquoted_icon(self):
        text = open(os.path.join(ROOT, "install.sh"),
                    encoding="utf-8").read()
        self.assertIn('echo "Exec=\\"$DIR/run.sh\\""', text)
        self.assertIn('ICON_LINE="Icon=$ICON_PATH"', text)


class ZipTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import build_zip
        cls.tmp = tempfile.mkdtemp(prefix="appimage-zip-")
        cls.zip_path = os.path.join(cls.tmp, "out.zip")
        build_zip.build(cls.zip_path)
        cls.zf = zipfile.ZipFile(cls.zip_path)
        cls.names = cls.zf.namelist()

    def test_top_level_folder(self):
        self.assertTrue(self.names)
        for name in self.names:
            self.assertTrue(
                name.startswith("appimage-run-helper/"), name)

    def test_modes_scripts_and_desktop_executable(self):
        for info in self.zf.infolist():
            mode = info.external_attr >> 16
            name = os.path.basename(info.filename)
            if name in build_zip_scripts() or \
                    name.endswith(".desktop"):
                self.assertEqual(
                    mode, 0o100755,
                    "%s stored as %o" % (info.filename, mode))
            elif name.endswith(".png"):
                self.assertEqual(mode, 0o100644, info.filename)
            else:
                self.assertEqual(
                    mode, 0o100644,
                    "%s stored as %o" % (info.filename, mode))

    def test_no_dev_or_secret_files(self):
        for name in self.names:
            base = os.path.basename(name)
            self.assertNotEqual(base, "BUILD_REPORT.md")
            self.assertNotEqual(base, "install.log")
            self.assertNotIn(".venv", name)
            self.assertNotIn("__pycache__", name)
            self.assertNotEqual(base, "providers.json")
            self.assertFalse(base.endswith(".pem"), name)
            self.assertFalse(base.endswith(".key"), name)
            self.assertFalse(base.endswith(".env"), name)

    def test_icons_packed(self):
        self.assertIn("appimage-run-helper/assets/appimage.png",
                      self.names)
        self.assertIn("appimage-run-helper/assets/appimage.svg",
                      self.names)

    def test_unzip_extract_keeps_desktop_executable(self):
        out = os.path.join(self.tmp, "extract")
        result = subprocess.run(
            ["unzip", "-q", self.zip_path, "-d", out],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        installer = os.path.join(
            out, "appimage-run-helper",
            "Install AppImage Runner.desktop")
        self.assertTrue(os.access(installer, os.X_OK),
                        "installer .desktop lost its exec bit")
        script = os.path.join(out, "appimage-run-helper",
                              "install.sh")
        self.assertTrue(os.access(script, os.X_OK))


def build_zip_scripts():
    import build_zip
    return build_zip.SCRIPTS


class TreeHygieneTests(unittest.TestCase):

    def test_no_binaries_in_tree(self):
        allowed_png = set()
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in (".venv", "__pycache__",
                                        ".git")]
            for name in filenames:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, ROOT)
                if name.endswith(".png"):
                    self.assertIn(rel, allowed_png,
                                  "PNG in tree: %s" % rel)
                self.assertFalse(name.endswith(".zip"), rel)
                self.assertFalse(name.endswith(".pyc"), rel)

    def test_no_em_dash_bytes_anywhere(self):
        for path in tree_text_files():
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertNotIn(
                EM_DASH_BYTES, data,
                "em-dash in %s" % os.path.relpath(path, ROOT))

    def test_no_todo_or_fixme(self):
        for path in all_text_files():
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn(MARKER_A, text, path)
            self.assertNotIn(MARKER_B, text, path)

    def test_gitignore_covers_secrets(self):
        text = open(os.path.join(ROOT, ".gitignore"),
                    encoding="utf-8").read()
        for entry in (".env", "providers.json", "*.pem", "*.key",
                      "id_rsa", "BUILD_REPORT.md", ".venv/",
                      "assets/*.png", "*.zip"):
            self.assertIn(entry, text)


class IconTests(unittest.TestCase):

    def test_svg_parses(self):
        import xml.etree.ElementTree as ET
        path = os.path.join(ROOT, "assets", "appimage.svg")
        tree = ET.parse(path)
        root = tree.getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.get("viewBox"), "0 0 256 256")

    def test_render_produces_pngs(self):
        out = tempfile.mkdtemp(prefix="appimage-icons-")
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["LD_LIBRARY_PATH"] = (
            "/home/hatch/workspace/qt-libs/root/usr/lib/"
            "x86_64-linux-gnu")
        env["__EGL_VENDOR_LIBRARY_DIRS"] = (
            "/home/hatch/workspace/qt-libs/root/usr/share/glvnd/"
            "egl_vendor.d")
        result = subprocess.run(
            [FORGE_PY, os.path.join(ROOT, "render_icons.py"), out],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        for size in (16, 32, 48, 64, 128, 256):
            path = os.path.join(out, "appimage-%d.png" % size)
            self.assertTrue(os.path.isfile(path), path)
            with open(path, "rb") as fh:
                header = fh.read(24)
            self.assertEqual(header[:8],
                             b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", header[16:24])
            self.assertEqual((width, height), (size, size))
        self.assertTrue(os.path.isfile(
            os.path.join(out, "appimage.png")))


class GuiImportBanTests(unittest.TestCase):
    """gui.py is a thin viewer: it must not import the core or
    the CLI. Parsed with ast so comments cannot fake it."""

    def test_gui_imports_no_core_or_cli(self):
        path = os.path.join(ROOT, "appimagehelper", "gui.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        banned = {"core", "cli"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[-1], banned,
                        "gui.py imports %s" % alias.name)
                    self.assertNotIn("appimagehelper.core",
                                     alias.name)
                    self.assertNotIn("appimagehelper.cli",
                                     alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn(
                    module.split(".")[-1], banned,
                    "gui.py imports from %s" % module)


class WrapperSymlinkTests(unittest.TestCase):

    def test_cli_through_symlink(self):
        linkdir = tempfile.mkdtemp(prefix="appimage-link-")
        link = os.path.join(linkdir, "appimagehelper-cli")
        os.symlink(os.path.join(ROOT, "appimagehelper-cli"), link)
        result = subprocess.run([link, "--help"],
                                capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("make-runnable", result.stdout)


class VersionConsistencyTests(unittest.TestCase):

    def test_versions_agree(self):
        sys.path.insert(0, ROOT)
        import appimagehelper
        version = appimagehelper.__version__
        changelog = open(os.path.join(ROOT, "CHANGELOG.md"),
                         encoding="utf-8").read()
        match = re.search(r"## \[(\d+\.\d+\.\d+)\]", changelog)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), version)
        import build_zip
        self.assertEqual(build_zip.ZIP_NAME,
                         "appimage-run-helper-v%s.zip" % version)
        readme = open(os.path.join(ROOT, "README.md"),
                      encoding="utf-8").read()
        self.assertIn("v%s" % version, readme)


if __name__ == "__main__":
    unittest.main()
