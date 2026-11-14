"""GUI tests (offscreen). Module-guarded: skip cleanly without PySide6.

The window is a thin viewer: it never reads text in-process.
Every test drives the real Read and Clean buttons against stub
tools placed on PATH (small executables that print canned JSON),
to check the window's parsing without waiting on real OCR and
without depending on Worker A's CLI or on a real tesseract
binary. Fixtures are empty files with image extensions: the
stubs never open them.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

# The Qt libs live extracted under ~/workspace/qt-libs (see
# AGENTS.md): point the loader at them before importing PySide6,
# so the suite also runs outside run_tests.sh.
_QT_LIB = os.path.expanduser(
    "~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu")
if os.path.isdir(_QT_LIB):
    _old_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _QT_LIB not in _old_ld.split(os.pathsep):
        os.environ["LD_LIBRARY_PATH"] = (
            _QT_LIB + os.pathsep + _old_ld if _old_ld else _QT_LIB)
    os.environ.setdefault(
        "__EGL_VENDOR_LIBRARY_DIRS",
        os.path.expanduser("~/workspace/qt-libs/root/usr/share"
                           "/glvnd/egl_vendor.d"))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    from PySide6.QtCore import (QLockFile, QMimeData, QPoint,
                                QSettings, QSize, Qt, QUrl)
    from PySide6.QtGui import QAction, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QMessageBox,
                                   QPushButton, QWidget)
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from ocrreader import gui  # noqa: E402
    from ocrreader.debug_log import DebugLogger  # noqa: E402

# Qt-free: settings and logsetup are importable without PySide6.
from ocrreader import logsetup  # noqa: E402
from ocrreader.settings import Settings  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(TREE, "tests", "single_instance_driver.py")

NOTE_TEXT = "This is a wrapped\nline of text\nfrom a note."
NOTE_CLEANED = "This is a wrapped line of text from a note."
CLEAN_TEXT = "Already tidy text."

# A stub reader: prints one canned result per path argument,
# keyed by the file name, so one run covers a wrapped note, an
# already tidy text, and an unreadable file.
STUB_READ = '''#!/usr/bin/env python3
import json, os, sys
results = []
skip_next = False
for path in sys.argv[1:]:
    if skip_next:
        skip_next = False
        continue
    if path == "--lang":
        skip_next = True
        continue
    if path.startswith("--"):
        continue
    name = os.path.basename(path)
    base = {"path": os.path.abspath(path), "file": name,
            "text": "", "pages": 1, "language": "eng",
            "error": None}
    if "note" in name:
        base["text"] = "This is a wrapped\\nline of text\\nfrom a note."
    elif "clean" in name:
        base["text"] = "Already tidy text."
    else:
        base.update(error="This file is not a readable image",
                    pages=0)
    results.append(base)
print(json.dumps(results))
'''

# A stub cleaner: joins the wrapped lines of the text file it is
# given and reports what it did, like the real clean command.
STUB_CLEAN = '''#!/usr/bin/env python3
import json, sys
path = [a for a in sys.argv[1:] if not a.startswith("--")][0]
with open(path, encoding="utf-8") as fh:
    text = fh.read()
lines = [ln for ln in text.splitlines() if ln.strip()]
joined = " ".join(lines)
changes = []
if len(lines) > 1:
    changes.append("joined %d wrapped lines" % len(lines))
print(json.dumps({"text": joined, "changes": changes}))
'''

# A stub reader that never finishes on its own: Cancel must
# kill it outright.
SLOW_STUB_READ = '''#!/usr/bin/env python3
import time
time.sleep(120)
print("[]")
'''

# A stub reader that fails the way a missing tesseract does: a
# plain message on stderr, exit 1, no JSON.
FAILING_STUB_READ = '''#!/usr/bin/env python3
import sys
print("tesseract is not installed. Install it with: "
      "sudo apt install tesseract-ocr", file=sys.stderr)
sys.exit(1)
'''


def wait_until(predicate, timeout=10.0):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(gui.DARK_STYLESHEET)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved_path = os.environ.get("PATH", "")
        self.ini_path = os.path.join(self.tmp.name, "settings.ini")
        self.qsettings = QSettings(self.ini_path,
                                   QSettings.IniFormat)
        self.settings = Settings(
            path=os.path.join(self.tmp.name, "settings.json"))
        self.logger = DebugLogger(
            "ocr-reader", "0.1.0",
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.windows = []
        # Fixtures are empty files with image extensions: the
        # stubs key on the name and never open them.
        self.note = self._fixture("note.png")
        self.clean_png = self._fixture("clean.png")
        self.bad = self._fixture("bad.png")

    def tearDown(self):
        os.environ["PATH"] = self._saved_path
        for window in self.windows:
            window.close()
        self.logger.uninstall_crash_handler()
        for handler in list(self.logger.logger.handlers):
            handler.close()
            self.logger.logger.removeHandler(handler)
        self.tmp.cleanup()

    def _fixture(self, name, folder=None):
        path = os.path.join(folder or self.tmp.name, name)
        Path(path).write_bytes(b"")
        return path

    def make_window(self):
        window = gui.MainWindow(settings=self.settings,
                                logger=self.logger,
                                qsettings=self.qsettings)
        self.windows.append(window)
        return window

    def install_stub(self, name, source):
        """Put a stub executable on PATH; returns its path."""
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR
                 | stat.S_IXGRP | stat.S_IXOTH)
        os.environ["PATH"] = bindir + os.pathsep + self._saved_path
        return path

    def run_stub_read(self, window, paths):
        """Read via the stub; wait until the text pane fills."""
        self.install_stub("ocr-read", STUB_READ)
        window.add_files(paths)
        window.read_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))

    def test_window_opens_with_default_size(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(1100, 650))

    def test_empty_state_shown_with_no_files(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.empty_label.isVisible())
        self.assertIn("No files yet",
                      window.empty_label.text())
        self.assertEqual(window.text_pane.toPlainText(), "")
        self.assertIn("Read text appears here",
                      window.text_pane.placeholderText())
        self.assertEqual(window.text_source_label.text(),
                         "No text yet.")
        self.assertFalse(window.read_button.isEnabled())
        self.assertFalse(window.clean_button.isEnabled())
        self.assertFalse(window.copy_button.isEnabled())
        self.assertFalse(window.save_button.isEnabled())
        self.assertFalse(window.cancel_button.isEnabled())
        self.assertTrue(window.add_button.isEnabled())

    def test_read_with_no_files_does_nothing(self):
        window = self.make_window()
        window.show()
        self.assertFalse(window.read_button.isEnabled())
        window._on_read()
        self.assertIsNone(window._worker)

    def test_nothing_selected_by_default(self):
        window = self.make_window()
        window.show()
        window.add_files([self.note])
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), -1)
        focused = QApplication.focusWidget()
        self.assertFalse(isinstance(focused, QPushButton))

    def test_click_selects_a_row(self):
        # The auto-select guard must not break real selection: a
        # click on a row selects it.
        window = self.make_window()
        window.show()
        window.add_files([self.note, self.clean_png])
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), -1)
        rect = window.file_list.visualItemRect(
            window.file_list.item(1))
        QTest.mouseClick(window.file_list.viewport(),
                         Qt.LeftButton, pos=rect.center())
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), 1)

    def test_add_files_adds_rows(self):
        window = self.make_window()
        window.show()
        added, failures = window.add_files([self.note])
        self.assertEqual((added, failures), (1, []))
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "note.png")
        self.assertFalse(window.empty_label.isVisible())
        self.assertTrue(window.read_button.isEnabled())
        # No text yet: Clean, Copy, and Save stay disabled.
        self.assertFalse(window.clean_button.isEnabled())
        self.assertFalse(window.copy_button.isEnabled())
        self.assertFalse(window.save_button.isEnabled())

    def test_add_files_skips_duplicates(self):
        window = self.make_window()
        window.add_files([self.note, self.note])
        self.assertEqual(window.file_list.count(), 1)

    def test_add_files_via_dialog(self):
        window = self.make_window()
        window.show()
        with mock.patch.object(
                gui.QFileDialog, "getOpenFileNames",
                return_value=([self.note], "")):
            window._on_add_files()
        self.assertEqual(window.file_list.count(), 1)

    def test_add_folder_adds_image_files(self):
        folder = os.path.join(self.tmp.name, "shots")
        os.mkdir(folder)
        self._fixture("shot1.png", folder)
        self._fixture("shot2.jpg", folder)
        self._fixture("doc.pdf", folder)
        self._fixture("notes.txt", folder)
        window = self.make_window()
        added, failures = window.add_files([folder])
        self.assertEqual((added, failures), (3, []))
        self.assertEqual(window.file_list.count(), 3)

    def test_add_pdf_file(self):
        # PDFs are first-class inputs: the engine reads them
        # page by page.
        pdf = self._fixture("scan.pdf")
        window = self.make_window()
        added, failures = window.add_files([pdf])
        self.assertEqual((added, failures), (1, []))
        self.assertEqual(window.file_list.item(0).text(),
                         "scan.pdf")

    def test_collect_inputs_rejects_non_images(self):
        # Pure function, no window: a text file and an empty
        # folder are failures, never rows.
        text = os.path.join(self.tmp.name, "notes.txt")
        Path(text).write_text("not an image\n", encoding="utf-8")
        empty = os.path.join(self.tmp.name, "empty")
        os.mkdir(empty)
        files, failures = gui.collect_inputs(
            [self.note, text, empty, "/no/such/file.png"])
        self.assertEqual(files, [self.note])
        self.assertEqual(len(failures), 3)

    def test_stub_read_fills_text_pane(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note, self.clean_png])
        # The first file's text shows, without selecting its row.
        self.assertEqual(window.text_pane.toPlainText(), NOTE_TEXT)
        self.assertEqual(window.text_source_label.text(),
                         "Text from: note.png")
        self.assertEqual(window.file_list.item(0).text(),
                         "note.png: 10 words")
        self.assertEqual(window.file_list.item(1).text(),
                         "clean.png: 3 words")
        self.assertEqual(window.file_list.currentRow(), -1)
        self.assertIn("Read 2 file(s), 13 words",
                      window.status_bar.currentMessage())
        self.assertFalse(window.busy_light.property("busy"))
        self.assertTrue(window.clean_button.isEnabled())
        self.assertTrue(window.copy_button.isEnabled())
        self.assertTrue(window.save_button.isEnabled())

    def test_stub_read_unreadable_file(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.bad])
        self.assertEqual(window.file_list.item(0).text(),
                         "bad.png: could not read")
        self.assertIn("1 could not be read",
                      window.status_bar.currentMessage())
        # The pane shows the plain error, and Clean stays off:
        # there is no text to tidy.
        self.assertIn("Could not read this file.",
                      window.text_pane.toPlainText())
        self.assertIn("not a readable image",
                      window.text_pane.toPlainText())
        self.assertFalse(window.clean_button.isEnabled())
        self.assertFalse(window.copy_button.isEnabled())
        self.assertFalse(window.save_button.isEnabled())

    def test_selecting_a_file_shows_its_text(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note, self.clean_png])
        self.assertEqual(window.text_pane.toPlainText(), NOTE_TEXT)
        rect = window.file_list.visualItemRect(
            window.file_list.item(1))
        QTest.mouseClick(window.file_list.viewport(),
                         Qt.LeftButton, pos=rect.center())
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), 1)
        self.assertEqual(window.text_pane.toPlainText(), CLEAN_TEXT)
        self.assertEqual(window.text_source_label.text(),
                         "Text from: clean.png")

    def test_stub_clean_tidies_text(self):
        self.install_stub("ocr-clean", STUB_CLEAN)
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note])
        self.assertEqual(window.text_pane.toPlainText(), NOTE_TEXT)
        window.clean_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        self.assertEqual(window.text_pane.toPlainText(),
                         NOTE_CLEANED)
        self.assertIn("joined 3 wrapped lines",
                      window.status_bar.currentMessage())
        # The word count is unchanged: clean tidied, it did not
        # rewrite.
        self.assertEqual(window.file_list.item(0).text(),
                         "note.png: 10 words")
        self.assertFalse(window.busy_light.property("busy"))

    def test_clean_disabled_with_no_text(self):
        window = self.make_window()
        window.show()
        self.assertFalse(window.clean_button.isEnabled())
        window._on_clean()
        self.assertIsNone(window._worker)

    def test_copy_copies_text(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note])
        window.copy_button.click()
        self.app.processEvents()
        self.assertEqual(QApplication.clipboard().text(),
                         NOTE_TEXT)
        self.assertIn("Copied the text",
                      window.status_bar.currentMessage())

    def test_save_writes_text(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note])
        out = os.path.join(self.tmp.name, "note.txt")
        self.assertTrue(window.save_text(out))
        self.assertEqual(
            Path(out).read_text(encoding="utf-8"), NOTE_TEXT)
        self.assertIn("Saved the text to note.txt",
                      window.status_bar.currentMessage())

    def test_save_via_dialog(self):
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note])
        out = os.path.join(self.tmp.name, "saved.txt")
        with mock.patch.object(
                gui.QFileDialog, "getSaveFileName",
                return_value=(out, "Text files (*.txt)")):
            window.save_button.click()
        self.app.processEvents()
        self.assertEqual(
            Path(out).read_text(encoding="utf-8"), NOTE_TEXT)

    def test_save_disabled_with_no_text(self):
        window = self.make_window()
        window.show()
        self.assertFalse(window.save_button.isEnabled())
        self.assertFalse(window.save_text(
            os.path.join(self.tmp.name, "note.txt")))

    def test_cancel_kills_the_read_subprocess(self):
        self.install_stub("ocr-read", SLOW_STUB_READ)
        window = self.make_window()
        window.show()
        window.add_files([self.note])
        window.read_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is not None
            and window._worker._proc is not None
            and window._worker._proc.poll() is None,
            timeout=15))
        proc = window._worker._proc
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        # SIGKILL: the subprocess died by signal 9, it did not
        # run to completion.
        self.assertEqual(proc.returncode, -9)
        self.assertFalse(window.busy_light.property("busy"))
        self.assertIn("cancelled",
                      window.status_bar.currentMessage().lower())

    def test_busy_light_is_on_while_reading(self):
        self.install_stub("ocr-read", SLOW_STUB_READ)
        window = self.make_window()
        window.show()
        window.add_files([self.note])
        window.read_button.click()
        # The worker starts on the next event loop turn; the busy
        # light is set synchronously in _on_read.
        self.assertTrue(window.busy_light.property("busy"))
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        self.assertFalse(window.busy_light.property("busy"))

    def test_read_failure_shows_plain_error(self):
        self.install_stub("ocr-read", FAILING_STUB_READ)
        window = self.make_window()
        window.show()
        window.add_files([self.note])
        window.read_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        message = window.status_bar.currentMessage()
        self.assertIn("tesseract is not installed", message)
        self.assertNotIn("Traceback", message)
        self.assertEqual(window.text_pane.toPlainText(), "")
        self.assertFalse(window.busy_light.property("busy"))

    def test_how_to_use_window_opens(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        self.assertIsNotNone(window._how_to_use)
        self.assertTrue(window._how_to_use.isVisible())
        self.assertIn("How to Use",
                      window._how_to_use.windowTitle())

    def test_caveat_is_visible_in_window_and_how_to_use(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        # In full, not clipped: the label holds the whole text
        # and wraps it.
        self.assertEqual(window.caveat_label.text(),
                         gui.CAVEAT_TEXT)
        self.assertTrue(window.caveat_label.wordWrap())
        texts = [w.toPlainText()
                 for w in window._how_to_use.findChildren(QWidget)
                 if hasattr(w, "toPlainText")]
        self.assertTrue(any(gui.CAVEAT_TEXT in t for t in texts))

    def test_clean_tooltip_says_never_rewrites_words(self):
        window = self.make_window()
        window.show()
        self.assertIn("never rewrites words",
                      window.clean_button.toolTip())
        self.assertIn("only tidies whitespace",
                      window.clean_button.toolTip())

    def test_menus_have_the_actions(self):
        window = self.make_window()
        bar = window.menuBar()
        found = {}
        for action in bar.actions():
            found[action.text()] = [a.text() for a in
                                    action.menu().actions()]
        self.assertIn("Add files", found["File"])
        self.assertIn("Save text", found["File"])
        self.assertIn("Generate debug report", found["File"])
        self.assertIn("Quit", found["File"])
        self.assertIn("How to Use", found["Help"])

    def test_geometry_memory_round_trips(self):
        # The offscreen platform's screen is 800x800 and
        # restoreGeometry clamps the restored width to it, so the
        # test uses a size that fits the sandbox screen. On his
        # real 1366x768 screen the default 1100x650 fits.
        window = self.make_window()
        window.show()
        window.resize(780, 600)
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(780, 600))
        window.close()
        self.app.processEvents()
        window2 = self.make_window()
        window2.show()
        self.app.processEvents()
        self.assertEqual(window2.size(), QSize(780, 600))

    def test_no_em_dash_in_visible_text(self):
        self.install_stub("ocr-clean", STUB_CLEAN)
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note, self.clean_png,
                                    self.bad])
        window.clean_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "\u2014" in t]
        self.assertEqual(offenders, [])

    def test_no_bare_ampersand_in_visible_labels(self):
        self.install_stub("ocr-clean", STUB_CLEAN)
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note, self.clean_png])
        window.clean_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "&" in t]
        self.assertEqual(offenders, [])

    def test_drag_and_drop_adds_files(self):
        window = self.make_window()
        window.show()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.note)])
        enter = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
        window.dropEvent(drop)
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "note.png")

    def test_no_unexpected_dialogs_during_read(self):
        self.install_stub("ocr-clean", STUB_CLEAN)
        window = self.make_window()
        window.show()
        self.run_stub_read(window, [self.note])
        window.clean_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        self.app.processEvents()
        self.assertIsNone(QApplication.activeModalWidget())
        visible_boxes = [
            w for w in QApplication.topLevelWidgets()
            if isinstance(w, QMessageBox) and w.isVisible()]
        self.assertEqual(visible_boxes, [])

    def test_single_instance_lock(self):
        # Second QLockFile fails while the first holds it.
        path = os.path.join(self.tmp.name, "single-instance.lock")
        first = QLockFile(path)
        first.setStaleLockTime(0)
        # This PySide6 build requires the timeout argument.
        self.assertTrue(first.tryLock(0))
        second = QLockFile(path)
        second.setStaleLockTime(0)
        self.assertFalse(second.tryLock(0))
        first.unlock()
        third = QLockFile(path)
        third.setStaleLockTime(0)
        self.assertTrue(third.tryLock(0))
        third.unlock()

    def test_try_single_instance(self):
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp.name,
                                                   "xdg-data")
        try:
            first = gui.try_single_instance()
            self.assertIsNotNone(first)
            second = gui.try_single_instance()
            self.assertIsNone(second)
            first.unlock()
        finally:
            if old is None:
                del os.environ["XDG_DATA_HOME"]
            else:
                os.environ["XDG_DATA_HOME"] = old

    def test_single_instance_second_launch_exits_zero(self):
        # Two real processes: a driver holds the lock, then a real
        # `python -m ocrreader.gui_main` launch must exit 0 while
        # the first stays alive.
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = os.path.join(self.tmp.name, "data")
        env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                              "config")
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["TMPDIR"] = "/tmp"
        ready = os.path.join(self.tmp.name, "lock-ready")
        driver_err = open(os.path.join(self.tmp.name,
                                       "driver-stderr.txt"), "w")
        driver = subprocess.Popen(
            [sys.executable, "-u", DRIVER, ready],
            cwd=TREE, env=env, stdout=subprocess.DEVNULL,
            stderr=driver_err)
        try:
            deadline = time.monotonic() + 60
            while not os.path.exists(ready):
                if driver.poll() is not None:
                    break
                if time.monotonic() > deadline:
                    break
                time.sleep(0.1)
            self.assertTrue(os.path.exists(ready),
                            "driver never took the lock; stderr: %s"
                            % Path(driver_err.name).read_text()
                            if os.path.exists(driver_err.name)
                            else "no driver log")
            self.assertIsNone(driver.poll())
            second = subprocess.run(
                [sys.executable, "-m", "ocrreader.gui_main"],
                cwd=TREE, env=env, capture_output=True, text=True,
                timeout=60)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already running", second.stderr)
            # The first process is still alive.
            self.assertIsNone(driver.poll())
        finally:
            driver.kill()
            driver.wait(timeout=10)
            driver_err.close()

    # -- helpers ------------------------------------------------------
    def _collect_visible_text(self, root):
        texts = []
        for widget in [root] + root.findChildren(QWidget):
            for getter in ("text", "windowTitle", "placeholderText",
                           "toolTip", "title", "currentText",
                           "currentMessage", "toPlainText"):
                func = getattr(widget, getter, None)
                if callable(func):
                    try:
                        value = func()
                    except Exception:
                        continue
                    if isinstance(value, str) and value:
                        texts.append(value)
        for action in root.findChildren(QAction):
            if action.text():
                texts.append(action.text())
        # File list rows are not widgets.
        file_list = getattr(root, "file_list", None)
        if file_list is not None:
            for row in range(file_list.count()):
                item = file_list.item(row)
                if item is not None and item.text():
                    texts.append(item.text())
        return texts


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ArgvTests(unittest.TestCase):
    """The CLI seam: argv shapes, without a window."""

    def test_read_argv_falls_back_without_wrapper(self):
        saved = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            argv = gui.read_argv(["a.png"])
            self.assertEqual(
                argv[:3], [sys.executable, "-m", "ocrreader"])
            self.assertEqual(argv[3:5], ["read", "--json"])
            self.assertEqual(argv[5:7], ["--lang", "eng"])
            self.assertEqual(argv[7:], ["a.png"])
        finally:
            os.environ["PATH"] = saved

    def test_read_argv_prefers_path_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "ocr-read")
            Path(stub).write_text("#!/bin/sh\necho '[]'\n",
                                  encoding="utf-8")
            os.chmod(stub, 0o755)
            saved = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + saved
                argv = gui.read_argv(["a.png"])
                self.assertEqual(argv[0], stub)
                self.assertEqual(argv[1], "--json")
                self.assertEqual(argv[2:4], ["--lang", "eng"])
            finally:
                os.environ["PATH"] = saved

    def test_read_argv_passes_language(self):
        argv = gui.read_argv(["a.png"], "fra")
        self.assertIn("--lang", argv)
        self.assertEqual(argv[argv.index("--lang") + 1], "fra")
        self.assertEqual(argv[-1], "a.png")

    def test_clean_argv_shape(self):
        saved = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            argv = gui.clean_argv("text.txt")
            self.assertEqual(
                argv[:3], [sys.executable, "-m", "ocrreader"])
            self.assertEqual(
                argv[3:], ["clean", "text.txt", "--json"])
        finally:
            os.environ["PATH"] = saved

    def test_clean_argv_prefers_path_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "ocr-clean")
            Path(stub).write_text(
                "#!/bin/sh\necho '{\"text\": \"\", "
                "\"changes\": []}'\n", encoding="utf-8")
            os.chmod(stub, 0o755)
            saved = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + saved
                argv = gui.clean_argv("text.txt")
                self.assertEqual(argv[0], stub)
                self.assertEqual(argv[1], "text.txt")
                self.assertEqual(argv[2], "--json")
            finally:
                os.environ["PATH"] = saved

    def test_word_count(self):
        self.assertEqual(gui.word_count(""), 0)
        self.assertEqual(gui.word_count("   "), 0)
        self.assertEqual(gui.word_count("one two  three"), 3)
        self.assertEqual(gui.word_count(NOTE_TEXT), 10)


class SettingsTests(unittest.TestCase):
    """Settings: path agreement with logsetup, language default."""

    def test_data_dir_matches_logsetup(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("XDG_DATA_HOME")
            try:
                os.environ["XDG_DATA_HOME"] = tmp
                from ocrreader.settings import data_dir
                self.assertEqual(data_dir(),
                                 logsetup.data_dir())
                self.assertEqual(
                    data_dir(),
                    os.path.join(tmp, "ocr-reader"))
            finally:
                if old is None:
                    del os.environ["XDG_DATA_HOME"]
                else:
                    os.environ["XDG_DATA_HOME"] = old
        # And without XDG_DATA_HOME set at all.
        old = os.environ.get("XDG_DATA_HOME")
        try:
            if "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]
            from ocrreader.settings import data_dir
            self.assertEqual(data_dir(), logsetup.data_dir())
        finally:
            if old is not None:
                os.environ["XDG_DATA_HOME"] = old

    def test_log_dir_matches_logsetup(self):
        from ocrreader.settings import log_dir
        self.assertEqual(log_dir(), logsetup.log_dir())

    def test_default_language_is_eng(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                path=os.path.join(tmp, "settings.json"))
            self.assertEqual(settings.language, "eng")
            self.assertIsNone(settings.last_folder)

    def test_language_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = Settings(path=path)
            settings.language = "fra"
            settings.last_folder = tmp
            settings.save()
            again = Settings(path=path)
            self.assertEqual(again.language, "fra")
            self.assertEqual(again.last_folder, tmp)

    def test_corrupt_settings_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            Path(path).write_text("not json at all",
                                  encoding="utf-8")
            settings = Settings(path=path)
            self.assertEqual(settings.language, "eng")
            self.assertIsNone(settings.last_folder)


if __name__ == "__main__":
    unittest.main()
