"""GUI tests: the thin viewer against a stubbed CLI.

A stub `appimagehelper-cli` on PATH prints canned JSON, so the
window's parsing and status text are checked without running a
real AppImage. The offscreen platform renders nothing to a
screen; the proof drive (tests/proof_drive.py) makes the
screenshots a human checks.
"""

import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings  # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel,  # noqa: E402
                               QPushButton)

from appimagehelper import gui  # noqa: E402
from appimagehelper.logsetup import make_logger  # noqa: E402
from appimagehelper.settings import Settings  # noqa: E402
from tests.helpers import make_fake_appimage  # noqa: E402

EM_DASH = "\u2014"  # the em-dash character, as an escape

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
        _app.setStyleSheet(gui.DARK_STYLESHEET)
    return _app


def wait_until(predicate, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        get_app().processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


STUB_OK = """#!/bin/sh
cat <<'JSON'
{"command": "launch", "path": "/tmp/Fake.AppImage",
 "made_runnable": true, "already": false, "pid": 4242,
 "running": true, "finished": false, "error": null}
JSON
"""

STUB_FAIL = """#!/bin/sh
cat <<'JSON'
{"command": "launch",
 "error": "Fake.AppImage stopped right away (exit 3)."}
JSON
exit 1
"""


class WindowFixture(unittest.TestCase):

    def setUp(self):
        get_app()
        self.tmp = tempfile.mkdtemp(prefix="appimage-gui-")
        self.settings = Settings(
            os.path.join(self.tmp, "settings.json"))
        self.logger = make_logger(
            log_dir_path=os.path.join(self.tmp, "logs"))
        self.qsettings = QSettings(
            os.path.join(self.tmp, "qt.ini"), QSettings.IniFormat)
        self.window = gui.MainWindow(
            settings=self.settings, logger=self.logger,
            qsettings=self.qsettings)
        self.addCleanup(self.window.close)

    def install_stub(self, body):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        stub = os.path.join(bindir, "appimagehelper-cli")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(stub, 0o755)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = bindir + os.pathsep + old
        self.addCleanup(os.environ.__setitem__, "PATH", old)


class ContentSizeTests(WindowFixture):
    """Dialogs sized to content (the FYRN anti-example rule):
    the window never opens smaller than its content needs."""

    def test_window_not_smaller_than_size_hint(self):
        self.window.show()
        get_app().processEvents()
        hint = self.window.sizeHint()
        self.assertGreaterEqual(self.window.width(), hint.width())
        self.assertGreaterEqual(self.window.height(),
                                hint.height())

    def test_wrapped_labels_fit_their_text(self):
        self.window.show()
        get_app().processEvents()
        for label in (self.window.instruction_label,
                      self.window.help_note,
                      self.window.status_label):
            needed = label.heightForWidth(label.width())
            self.assertGreaterEqual(
                label.height() + 2, needed,
                "%s clips its text" % label.objectName())

    def test_how_to_use_not_smaller_than_content(self):
        from PySide6.QtWidgets import QTextEdit
        how = gui.HowToUseWindow(self.window)
        self.addCleanup(how.close)
        how.show()
        get_app().processEvents()
        hint = how.minimumSizeHint()
        self.assertGreaterEqual(how.width(), hint.width())
        self.assertGreaterEqual(how.height(), hint.height())
        editors = how.findChildren(QTextEdit)
        self.assertEqual(len(editors), 1)
        self.assertIn("File Transfer", editors[0].toPlainText())


class VisibleTextTests(WindowFixture):

    def _all_text(self):
        texts = [self.window.windowTitle()]
        for widget in self.window.findChildren(QObject):
            text = getattr(widget, "text", None)
            if callable(text):
                try:
                    value = text()
                except Exception:
                    continue
                if isinstance(value, str) and value:
                    texts.append(value)
        for action in self.window.menuBar().actions():
            texts.append(action.text())
            if action.menu():
                for sub in action.menu().actions():
                    texts.append(sub.text())
        texts.append(gui.HOW_TO_USE_TEXT)
        return texts

    def test_no_em_dash_in_visible_text(self):
        for text in self._all_text():
            self.assertNotIn(EM_DASH, text)

    def test_no_bare_ampersand_in_labels_and_buttons(self):
        widgets = self.window.findChildren(QLabel) + \
            self.window.findChildren(QPushButton)
        self.assertTrue(widgets)
        for widget in widgets:
            self.assertNotIn("&", widget.text(),
                             widget.objectName())

    def test_phone_checklist_in_help_note(self):
        note = self.window.help_note.text()
        self.assertIn("Plug the phone in", note)
        self.assertIn("File Transfer", note)
        self.assertIn("charge", note)


class PickAndRunTests(WindowFixture):

    def test_run_disabled_until_pick(self):
        self.assertFalse(self.window.run_button.isEnabled())
        _tmp, path = make_fake_appimage("exit 0\n")
        self.assertTrue(self.window.pick_file(path))
        self.assertTrue(self.window.run_button.isEnabled())
        self.assertIn("Fake.AppImage",
                      self.window.file_label.text())

    def test_pick_non_appimage_warns_but_allows(self):
        _tmp, path = make_fake_appimage(
            "exit 0\n", name="plainfile")
        self.assertTrue(self.window.pick_file(path))
        self.assertIn("does not look like an AppImage",
                      self.window.status_label.text())
        self.assertTrue(self.window.run_button.isEnabled())

    def test_pick_folder_rejected(self):
        self.assertFalse(self.window.pick_file(self.tmp))
        self.assertIn("not a file",
                      self.window.status_label.text())
        self.assertFalse(self.window.run_button.isEnabled())

    def test_pick_remembers_folder(self):
        _tmp, path = make_fake_appimage("exit 0\n")
        self.window.pick_file(path)
        self.assertEqual(self.settings.last_folder,
                         os.path.dirname(os.path.abspath(path)))

    def test_run_with_stub_cli_reports_running(self):
        self.install_stub(STUB_OK)
        _tmp, path = make_fake_appimage("exit 0\n")
        self.window.pick_file(path)
        self.window.run_button.click()
        self.assertTrue(
            wait_until(lambda: self.window._worker is None),
            "worker never finished")
        status = self.window.status_label.text()
        self.assertIn("running now", status)
        self.assertIn("Made", status)

    def test_run_with_stub_cli_reports_error(self):
        self.install_stub(STUB_FAIL)
        _tmp, path = make_fake_appimage("exit 0\n")
        self.window.pick_file(path)
        self.window.run_button.click()
        self.assertTrue(
            wait_until(lambda: self.window._worker is None),
            "worker never finished")
        self.assertIn("stopped right away",
                      self.window.status_label.text())
        self.assertTrue(self.window.run_button.isEnabled())


class CliCommandTests(unittest.TestCase):

    def test_launch_argv_shape_with_stub(self):
        tmp = tempfile.mkdtemp(prefix="appimage-argv-")
        stub = os.path.join(tmp, "appimagehelper-cli")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, stat.S_IRWXU)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = tmp + os.pathsep + old
        try:
            argv = gui.launch_argv("/x/Y.AppImage")
        finally:
            os.environ["PATH"] = old
        self.assertEqual(argv[0], stub)
        self.assertEqual(argv[1:], ["launch", "--json",
                                    "/x/Y.AppImage"])

    def test_is_appimage_name(self):
        self.assertTrue(gui.is_appimage_name("a/B.AppImage"))
        self.assertFalse(gui.is_appimage_name("a/b.txt"))


if __name__ == "__main__":
    unittest.main()
