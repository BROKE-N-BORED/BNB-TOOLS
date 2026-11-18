"""GUI entry tests: --help without Qt, and the missing
toolkit guard (plain words, exit 1, never a traceback).
"""

import os
import subprocess
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

TOOL_DIR = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

# An import blocker: any import of the named modules raises
# ImportError with the module's name attached, as if the
# package were not installed at all.
BLOCKER = textwrap.dedent("""
    import sys
    class Blocker:
        BLOCKED = %r
        def find_spec(self, fullname, path=None, target=None):
            for name in self.BLOCKED:
                if fullname == name or fullname.startswith(
                        name + "."):
                    raise ImportError(
                        "No module named %%r (blocked for test)"
                        %% fullname, name=fullname)
            return None
    sys.meta_path.insert(0, Blocker())
""")


def run_blocked(blocked, snippet, timeout=60):
    """Run a snippet in a subprocess with modules blocked."""
    code = BLOCKER % (tuple(blocked),)
    code += "sys.path.insert(0, %r)\n" % TOOL_DIR
    code += textwrap.dedent(snippet)
    return subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True,
                          timeout=timeout)


class GuiMainTests(unittest.TestCase):
    def test_help_answers_without_qt(self):
        # --help must work even where the toolkit is missing.
        result = run_blocked(["PySide6"], """
            from preloadchecks import gui_main
            sys.exit(gui_main.main(["--help"]))
        """)
        self.assertEqual(result.returncode, 0)
        self.assertIn("kill-picker", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_toolkit_is_plain_words_exit_1(self):
        # The missing-dependency guard: plain words naming the
        # missing piece and the install path, exit 1, no
        # traceback.
        result = run_blocked(["PySide6"], """
            from preloadchecks import gui_main
            sys.exit(gui_main.main([]))
        """)
        self.assertEqual(result.returncode, 1)
        self.assertIn("interface toolkit", result.stderr)
        self.assertIn("Install Pre-Load Model Checks",
                      result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(HAVE_QT, "PySide6 not installed")
    def test_help_in_process(self):
        from preloadchecks import gui_main
        self.assertEqual(gui_main.main(["--help"]), 0)

    @unittest.skipUnless(HAVE_QT, "PySide6 not installed")
    def test_bad_option_is_exit_2(self):
        from preloadchecks import gui_main
        self.assertEqual(gui_main.main(["--nope"]), 2)


class MainModuleGuardTests(unittest.TestCase):
    def test_missing_cli_dependency_is_plain_words_exit_1(self):
        # The __main__ guard: a module the CLI needs is missing,
        # so the entry point says so in plain words instead of
        # a traceback. json stands in for the missing module.
        result = run_blocked(["json"], """
            from preloadchecks import __main__ as entry
            sys.exit(entry.main(["--help"]))
        """)
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs json", result.stderr)
        self.assertIn("Install Pre-Load Model Checks",
                      result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_module_help_works(self):
        result = subprocess.run(
            [sys.executable, "-m", "preloadchecks", "--help"],
            capture_output=True, text=True, timeout=60,
            cwd=TOOL_DIR)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ram", result.stdout)
        self.assertIn("processes", result.stdout)
        self.assertIn("suitability", result.stdout)
        self.assertIn("kill", result.stdout)
        self.assertIn("watchdog", result.stdout)


if __name__ == "__main__":
    unittest.main()
