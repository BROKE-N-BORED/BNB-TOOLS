"""Packaging tests: version agreement, the unmodified T21
debug layer, import bans, no em-dashes, tree hygiene.
"""

import hashlib
import os
import re
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from preloadchecks import __version__  # noqa: E402

TOOL_DIR = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))
PKG_DIR = os.path.join(TOOL_DIR, "preloadchecks")

# T21's debug_log.py, unmodified. Any change to this file is a
# fork, not the shared layer.
T21_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")

# Scripts that must ship executable (in the tree and in the zip).
SCRIPTS = ("install.sh", "run.sh", "uninstall.sh",
           "run_tests.sh", "build_zip.py", "render_icons.py",
           "preload-checks", "preloadchecks-cli", "ram-check",
           "process-check", "suitability-check",
           "model-watchdog", "kill-picker")

SKIP_DIRS = {"__pycache__", ".venv", ".git", "logs"}


def tree_files():
    """Every file in the tool tree, skipping build byproducts."""
    out = []
    for root, dirs, files in os.walk(TOOL_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            out.append(os.path.join(root, name))
    return out


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class VersionTests(unittest.TestCase):
    def test_changelog_matches_package_version(self):
        text = read_text(os.path.join(TOOL_DIR, "CHANGELOG.md"))
        match = re.search(r"^## ([0-9]+\.[0-9]+\.[0-9]+)",
                          text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)

    def test_zip_name_matches_package_version(self):
        text = read_text(os.path.join(TOOL_DIR, "build_zip.py"))
        match = re.search(r'ZIP_NAME = "pre-load-model-checks-v'
                          r'([0-9]+\.[0-9]+\.[0-9]+)\.zip"',
                          text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)


class DebugLogTests(unittest.TestCase):
    def test_debug_log_is_unmodified_t21(self):
        path = os.path.join(PKG_DIR, "debug_log.py")
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(digest, T21_DEBUG_LOG_SHA256)


class ImportBanTests(unittest.TestCase):
    def test_gui_never_reads_proc_or_kills(self):
        # The window is a thin viewer: no /proc reads, no kills,
        # no subprocesses, no file opens of its own. ("/proc/"
        # with the slash: the module docstring mentions /proc
        # in words, which is documentation, not a read.)
        text = read_text(os.path.join(PKG_DIR, "gui.py"))
        for banned in ("/proc/", "os.kill", "subprocess",
                       "open("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)

    def test_killer_has_no_gui_imports(self):
        text = read_text(os.path.join(PKG_DIR, "killer.py"))
        self.assertNotIn("PySide6", text)
        self.assertNotIn("Qt", text)

    def test_cli_has_no_gui_imports(self):
        text = read_text(os.path.join(PKG_DIR, "cli.py"))
        self.assertNotIn("PySide6", text)

    def test_gui_main_imports_qt_only_inside_main(self):
        # The guarded entry: no Qt import at module level, so
        # --help answers on a machine without the toolkit.
        text = read_text(os.path.join(PKG_DIR, "gui_main.py"))
        lines = text.splitlines()
        top_level_qt = [line for line in lines
                        if line.startswith("import ")
                        and "PySide6" in line
                        or line.startswith("from PySide6")]
        self.assertEqual(top_level_qt, [])


class TextHygieneTests(unittest.TestCase):
    def test_no_em_dashes_anywhere(self):
        # debug_log.py is the shared T21 layer, copied
        # unmodified by rule: its own docstrings carry
        # em-dashes, and editing it would fork the layer.
        # Both check strings are built with chr() so this
        # test file holds no em-dash and no escape form
        # itself to trip on.
        em_dash = chr(0x2014)
        escape = chr(0x5c) + "u2014"
        for path in tree_files():
            if os.path.basename(path) == "debug_log.py":
                continue
            with self.subTest(path=os.path.relpath(path, TOOL_DIR)):
                text = read_text(path)
                self.assertNotIn(em_dash, text)
                self.assertNotIn(escape, text)

    def test_no_secret_shaped_literals_in_tests(self):
        # Push secret-scanning rejects secret-shaped literals
        # even in tests (T27 lesson): fixtures must be built
        # from parts, never written out whole.
        tests_dir = os.path.join(TOOL_DIR, "tests")
        pattern = re.compile(
            r"ghp_[A-Za-z0-9]{20,}|"
            r"sk-[A-Za-z0-9]{20,}|"
            r"AKIA[A-Z0-9]{16}")
        for name in os.listdir(tests_dir):
            if not name.endswith(".py"):
                continue
            text = read_text(os.path.join(tests_dir, name))
            self.assertIsNone(pattern.search(text), name)

    def test_no_binaries_or_logs_in_tree(self):
        for path in tree_files():
            with self.subTest(path=os.path.relpath(path, TOOL_DIR)):
                self.assertFalse(path.endswith(".zip"),
                                 "a zip in the tree fails hygiene")
                self.assertFalse(path.endswith(".png"),
                                 "rendered icons never land in tree")
                self.assertFalse(path.endswith(".log"),
                                 "logs never land in the tree")
                self.assertFalse(path.endswith(".pyc"))

    def test_no_build_report_in_zip_set(self):
        # BUILD_REPORT.md is excluded from pushes; the zip
        # builder must skip it too.
        text = read_text(os.path.join(TOOL_DIR, "build_zip.py"))
        self.assertIn('"BUILD_REPORT.md"', text)


class ScriptModeTests(unittest.TestCase):
    def test_scripts_are_executable_on_disk(self):
        for name in SCRIPTS:
            path = os.path.join(TOOL_DIR, name)
            with self.subTest(script=name):
                self.assertTrue(os.path.isfile(path))
                mode = os.stat(path).st_mode
                self.assertTrue(mode & stat.S_IXUSR,
                                "%s has no exec bit" % name)

    def test_zip_builder_knows_every_script(self):
        text = read_text(os.path.join(TOOL_DIR, "build_zip.py"))
        for name in SCRIPTS:
            with self.subTest(script=name):
                self.assertIn('"%s"' % name, text)


class DesktopTemplateTests(unittest.TestCase):
    def test_installer_exec_matches_fixed_template(self):
        # The S6 fixed template: the empty-%k fallback uses
        # os.getcwd() directly, never dirname() on it.
        skills_dir = os.path.abspath(os.path.join(
            TOOL_DIR, "..", "..", "bnb-skills"))
        template = os.path.join(
            skills_dir, "linux-release-packaging", "references",
            "desktop-entry-template.desktop")
        if not os.path.isfile(template):
            self.skipTest("S6 template not in this checkout")
        ours = read_text(os.path.join(
            TOOL_DIR, "Install Pre-Load Model Checks.desktop"))
        theirs = read_text(template)
        our_exec = [line for line in ours.splitlines()
                    if line.startswith("Exec=")]
        their_exec = [line for line in theirs.splitlines()
                      if line.startswith("Exec=")]
        self.assertEqual(len(our_exec), 1)
        self.assertEqual(len(their_exec), 1)
        self.assertEqual(our_exec[0], their_exec[0])


class ReadmeTests(unittest.TestCase):
    def test_readme_documents_the_chain(self):
        text = read_text(os.path.join(TOOL_DIR, "README.md"))
        for piece in ("ram-check", "process-check",
                      "suitability-check", "kill-picker",
                      "model-watchdog"):
            self.assertIn(piece, text)

    def test_readme_names_the_guards(self):
        text = read_text(os.path.join(TOOL_DIR, "README.md"))
        for guard in ("PID 1", "kernel threads",
                      "another user"):
            self.assertIn(guard, text)


if __name__ == "__main__":
    unittest.main()
