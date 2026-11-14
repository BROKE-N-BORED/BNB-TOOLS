"""GUI tests (offscreen). Module-guarded: skip cleanly without PySide6.

The window is a thin viewer: it never analyzes in-process. Most
tests drive the real Analyze button against a stub analyzer
placed on PATH (a small executable that prints canned JSON), to
check the window's parsing without waiting on real analysis.
test_real_analyze_end_to_end runs the real analyze subprocess
over generated fixtures and is the one test that must never be
stubbed. Fixtures come from helpers.py (Worker A's generators);
no binary fixtures live in the tree.
"""

import csv
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402

try:
    from PySide6.QtCore import (QLockFile, QMimeData, QPoint,
                                QSettings, QSize, Qt, QUrl)
    from PySide6.QtGui import QAction, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from songkey import gui  # noqa: E402
    from songkey.debug_log import DebugLogger  # noqa: E402
    from songkey.settings import Settings  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(TREE, "tests", "single_instance_driver.py")

# A stub analyzer: prints one canned result per path argument,
# keyed by the file name, so one run covers a measured BPM, a
# low-confidence key with a runner-up, and an unreadable file.
STUB_ANALYZE = '''#!/usr/bin/env python3
import json, os, sys
results = []
for path in sys.argv[1:]:
    if path.startswith("--"):
        continue
    name = os.path.basename(path)
    base = {"path": os.path.abspath(path), "file": name,
            "bpm": None, "bpm_confidence": "unknown",
            "tempo_bpm": None, "key": None,
            "key_confidence": "unknown", "key_score": None,
            "key_margin": None, "key_runner_up": None,
            "duration": 10.0, "error": None}
    if "click" in name:
        base.update(bpm=120.0, bpm_confidence="high",
                    tempo_bpm=120.1, duration=10.0)
    elif "minor" in name:
        base.update(key="A minor", key_confidence="low",
                    key_score=0.68, key_margin=0.037,
                    key_runner_up="C major", duration=8.0)
    else:
        base.update(error="Could not decode %s" % name,
                    duration=None)
    results.append(base)
print(json.dumps(results))
'''

# A stub analyzer that never finishes on its own: Cancel must
# kill it outright.
SLOW_STUB_ANALYZE = '''#!/usr/bin/env python3
import time
time.sleep(120)
print("[]")
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
            "song-key-bpm", "0.1.0",
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.windows = []
        self.click = helpers.make_fixture("click120", self.tmp.name)
        self.aminor = helpers.make_fixture("aminor", self.tmp.name)

    def tearDown(self):
        os.environ["PATH"] = self._saved_path
        for window in self.windows:
            window.close()
        self.logger.uninstall_crash_handler()
        for handler in list(self.logger.logger.handlers):
            handler.close()
            self.logger.logger.removeHandler(handler)
        self.tmp.cleanup()

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

    def cell(self, window, row, column):
        return window.results_table.item(row, column).text()

    def run_stub_analyze(self, window, paths):
        """Analyze via the stub; wait until the table fills."""
        self.install_stub("song-key-analyze", STUB_ANALYZE)
        window.add_files(paths)
        window.analyze_button.click()
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
        self.assertEqual(window.results_table.rowCount(), 0)
        self.assertEqual(window.results_table.columnCount(), 5)
        headers = [window.results_table.horizontalHeaderItem(i).text()
                   for i in range(5)]
        self.assertEqual(headers, ["File", "BPM", "Key",
                                   "Confidence", "Duration"])

    def test_analyze_with_no_files_does_nothing(self):
        window = self.make_window()
        window.show()
        self.assertFalse(window.analyze_button.isEnabled())
        window._on_analyze()
        self.assertIsNone(window._worker)

    def test_nothing_selected_by_default(self):
        window = self.make_window()
        window.show()
        window.add_files([self.click])
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), -1)
        self.assertEqual(
            window.results_table.selectedItems(), [])
        self.assertEqual(window.results_table.currentRow(), -1)
        focused = QApplication.focusWidget()
        self.assertFalse(isinstance(focused, QPushButton))

    def test_click_selects_a_row(self):
        # The auto-select guard must not break real selection: a
        # click on a row selects it.
        window = self.make_window()
        window.show()
        window.add_files([self.click, self.aminor])
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
        added, failures = window.add_files([self.click])
        self.assertEqual((added, failures), (1, []))
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "click120.wav")
        self.assertFalse(window.empty_label.isVisible())
        # The table matches the file list: one row of dashes
        # until the file is analyzed.
        self.assertEqual(window.results_table.rowCount(), 1)
        self.assertEqual(self.cell(window, 0, 0), "click120.wav")
        self.assertEqual(self.cell(window, 0, 1), "-")

    def test_add_files_skips_duplicates(self):
        window = self.make_window()
        window.add_files([self.click, self.click])
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.results_table.rowCount(), 1)

    def test_add_folder_adds_audio_files(self):
        folder = os.path.join(self.tmp.name, "songs")
        os.mkdir(folder)
        helpers.make_fixture("click147", folder)
        helpers.make_fixture("combo", folder)
        window = self.make_window()
        added, failures = window.add_files([folder])
        self.assertEqual((added, failures), (2, []))
        self.assertEqual(window.file_list.count(), 2)

    def test_collect_audio_rejects_non_audio(self):
        # Pure function, no window: a text file and an empty
        # folder are failures, never rows.
        text = os.path.join(self.tmp.name, "notes.txt")
        Path(text).write_text("not audio\n", encoding="utf-8")
        empty = os.path.join(self.tmp.name, "empty")
        os.mkdir(empty)
        files, failures = gui.collect_audio(
            [self.click, text, empty, "/no/such/file.wav"])
        self.assertEqual(files, [self.click])
        self.assertEqual(len(failures), 3)

    def test_stub_analyze_fills_table(self):
        window = self.make_window()
        window.show()
        self.run_stub_analyze(window, [self.click, self.aminor])
        self.assertEqual(window.results_table.rowCount(), 2)
        # Click track: measured BPM, no key.
        self.assertEqual(self.cell(window, 0, 0), "click120.wav")
        self.assertEqual(self.cell(window, 0, 1), "120.0")
        self.assertEqual(self.cell(window, 0, 2), "Unknown")
        self.assertEqual(self.cell(window, 0, 3), "Unknown")
        self.assertEqual(self.cell(window, 0, 4), "10.0 s")
        # Low-confidence key: the runner-up shows in the cell.
        self.assertEqual(self.cell(window, 1, 0), "aminor.wav")
        self.assertEqual(self.cell(window, 1, 1), "Unknown")
        self.assertEqual(self.cell(window, 1, 2),
                         "A minor (or C major?)")
        self.assertEqual(self.cell(window, 1, 3), "Low")
        self.assertEqual(self.cell(window, 1, 4), "8.0 s")
        # The file list carries the same verdicts.
        self.assertEqual(window.file_list.item(0).text(),
                         "click120.wav: 120.0 BPM, key unknown")
        self.assertEqual(window.file_list.item(1).text(),
                         "aminor.wav: BPM unknown, A minor")
        self.assertIn("Analyzed 2 file(s)",
                      window.status_bar.currentMessage())
        self.assertFalse(window.busy_light.property("busy"))
        self.assertTrue(window.export_button.isEnabled())
        # Nothing is selected after the fill.
        self.assertEqual(
            window.results_table.selectedItems(), [])

    def test_stub_analyze_unreadable_file(self):
        bad = os.path.join(self.tmp.name, "broken.wav")
        Path(bad).write_bytes(b"this is not audio")
        window = self.make_window()
        window.show()
        self.run_stub_analyze(window, [bad])
        self.assertEqual(self.cell(window, 0, 2), "Could not read")
        self.assertEqual(self.cell(window, 0, 3), "Error")
        self.assertEqual(window.file_list.item(0).text(),
                         "broken.wav: could not read")
        self.assertIn("1 could not be read",
                      window.status_bar.currentMessage())

    def test_real_analyze_end_to_end(self):
        # The one test that must run the REAL analyze
        # subprocess: no stub on PATH here.
        self.assertIsNone(shutil.which("song-key-analyze"))
        window = self.make_window()
        window.show()
        window.add_files([self.click, self.aminor])
        window.analyze_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=120))
        self.assertEqual(window.results_table.rowCount(), 2)
        bpm = float(self.cell(window, 0, 1))
        self.assertAlmostEqual(bpm, 120.0, delta=2.0)
        self.assertIn("A minor", self.cell(window, 1, 2))
        self.assertEqual(self.cell(window, 1, 1), "Unknown")
        self.assertIn("Analyzed 2 file(s)",
                      window.status_bar.currentMessage())

    def test_cancel_kills_the_analyze_subprocess(self):
        self.install_stub("song-key-analyze", SLOW_STUB_ANALYZE)
        window = self.make_window()
        window.show()
        window.add_files([self.click])
        window.analyze_button.click()
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
        self.assertIn("Analyze cancelled",
                      window.status_bar.currentMessage())

    def test_busy_light_is_on_while_analyzing(self):
        self.install_stub("song-key-analyze", SLOW_STUB_ANALYZE)
        window = self.make_window()
        window.show()
        window.add_files([self.click])
        window.analyze_button.click()
        # The worker starts on the next event loop turn; the busy
        # light is set synchronously in _on_analyze.
        self.assertTrue(window.busy_light.property("busy"))
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        self.assertFalse(window.busy_light.property("busy"))

    def test_export_writes_csv(self):
        # The analyze side is stubbed; the export side is the
        # REAL export subprocess over the window's results.
        window = self.make_window()
        window.show()
        self.run_stub_analyze(window, [self.click, self.aminor])
        out = os.path.join(self.tmp.name, "table.csv")
        self.assertTrue(window.export_results(out))
        self.assertTrue(wait_until(
            lambda: os.path.exists(out) and window._worker is None,
            timeout=30))
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["file", "bpm", "bpm_confidence",
                                   "key", "key_confidence",
                                   "key_runner_up", "duration"])
        self.assertEqual(rows[1][0], "click120.wav")
        self.assertEqual(rows[1][1], "120.0")
        self.assertEqual(rows[2][0], "aminor.wav")
        self.assertEqual(rows[2][3], "A minor")
        self.assertEqual(rows[2][4], "low")
        self.assertEqual(rows[2][5], "C major")
        self.assertIn("Exported 2 result(s) to table.csv",
                      window.status_bar.currentMessage())

    def test_export_disabled_with_no_results(self):
        window = self.make_window()
        window.show()
        self.assertFalse(window.export_button.isEnabled())
        self.assertFalse(window.export_results(
            os.path.join(self.tmp.name, "table.csv")))

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
        self.assertIn(gui.CAVEAT_TEXT, window.caveat_label.text())
        texts = [w.toPlainText()
                 for w in window._how_to_use.findChildren(QWidget)
                 if hasattr(w, "toPlainText")]
        self.assertTrue(any(gui.CAVEAT_TEXT in t for t in texts))

    def test_menus_have_the_actions(self):
        window = self.make_window()
        bar = window.menuBar()
        found = {}
        for action in bar.actions():
            found[action.text()] = [a.text() for a in
                                    action.menu().actions()]
        self.assertIn("Add files", found["File"])
        self.assertIn("Analyze", found["File"])
        self.assertIn("Export results", found["File"])
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
        window = self.make_window()
        window.show()
        self.run_stub_analyze(window, [self.click, self.aminor])
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "\u2014" in t]
        self.assertEqual(offenders, [])

    def test_no_bare_ampersand_in_visible_labels(self):
        window = self.make_window()
        window.show()
        self.run_stub_analyze(window, [self.click, self.aminor])
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
        mime.setUrls([QUrl.fromLocalFile(self.click)])
        enter = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
        window.dropEvent(drop)
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "click120.wav")

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
        # `python -m songkey` launch must exit 0 while the first
        # stays alive.
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
                [sys.executable, "-m", "songkey"],
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
                           "toPlainText"):
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
        # Table cells and headers are not widgets.
        table = getattr(root, "results_table", None)
        if table is not None:
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is not None and item.text():
                        texts.append(item.text())
            for col in range(table.columnCount()):
                header = table.horizontalHeaderItem(col)
                if header is not None and header.text():
                    texts.append(header.text())
        return texts


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class FormatTests(unittest.TestCase):
    """The table formatters, without a window."""

    def _result(self, **overrides):
        result = {"path": "/tmp/song.wav", "file": "song.wav",
                  "bpm": None, "bpm_confidence": "unknown",
                  "tempo_bpm": None, "key": None,
                  "key_confidence": "unknown", "key_score": None,
                  "key_margin": None, "key_runner_up": None,
                  "duration": None, "error": None}
        result.update(overrides)
        return result

    def test_format_bpm(self):
        self.assertEqual(gui.format_bpm(self._result()), "Unknown")
        self.assertEqual(
            gui.format_bpm(self._result(
                bpm=147.3, bpm_confidence="high")), "147.3")
        self.assertEqual(
            gui.format_bpm(self._result(
                bpm=147.3, bpm_confidence="low")), "147.3 (low)")

    def test_format_key(self):
        self.assertEqual(gui.format_key(self._result()), "Unknown")
        self.assertEqual(
            gui.format_key(self._result(
                key="D major", key_confidence="high")), "D major")
        self.assertEqual(
            gui.format_key(self._result(
                key="A minor", key_confidence="low",
                key_runner_up="C major")),
            "A minor (or C major?)")
        # Low confidence with no runner-up: the key alone.
        self.assertEqual(
            gui.format_key(self._result(
                key="E minor", key_confidence="low")), "E minor")
        self.assertEqual(
            gui.format_key(self._result(error="nope")),
            "Could not read")

    def test_format_confidence(self):
        self.assertEqual(
            gui.format_confidence(self._result()), "Unknown")
        self.assertEqual(
            gui.format_confidence(self._result(
                key_confidence="high")), "Confident")
        self.assertEqual(
            gui.format_confidence(self._result(
                key_confidence="low")), "Low")
        self.assertEqual(
            gui.format_confidence(self._result(error="nope")),
            "Error")

    def test_format_duration(self):
        self.assertEqual(
            gui.format_duration(self._result()), "Unknown")
        self.assertEqual(
            gui.format_duration(self._result(duration=30.0)),
            "30.0 s")

    def test_analyze_argv_falls_back_without_wrapper(self):
        saved = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            argv = gui.analyze_argv(["a.wav"])
            self.assertEqual(
                argv[:3], [sys.executable, "-m", "songkey"])
            self.assertEqual(argv[3:5], ["analyze", "--json"])
            self.assertEqual(argv[5:], ["a.wav"])
        finally:
            os.environ["PATH"] = saved

    def test_analyze_argv_prefers_path_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "song-key-analyze")
            Path(stub).write_text("#!/bin/sh\necho '[]'\n",
                                  encoding="utf-8")
            os.chmod(stub, 0o755)
            saved = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + saved
                argv = gui.analyze_argv(["a.wav"])
                self.assertEqual(argv[0], stub)
                self.assertEqual(argv[1], "--json")
            finally:
                os.environ["PATH"] = saved

    def test_export_argv_shape(self):
        saved = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            argv = gui.export_argv("results.json", "table.csv")
            self.assertEqual(
                argv[:3], [sys.executable, "-m", "songkey"])
            self.assertEqual(
                argv[3:],
                ["export", "results.json", "--format", "csv",
                 "--out", "table.csv"])
        finally:
            os.environ["PATH"] = saved


if __name__ == "__main__":
    unittest.main()
