"""GUI tests (offscreen). Module-guarded: skip cleanly without PySide6."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    from PySide6.QtCore import (QLockFile, QMimeData, QPoint,
                                QSettings, QSize, Qt, QUrl)
    from PySide6.QtGui import QAction, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from helpers import (FAKE_AWS, make_text_file,  # noqa: E402
                     sample_innocent_text,
                     sample_log_with_secrets)

if HAVE_QT:
    from scrubber import gui  # noqa: E402
    from scrubber.debug_log import DebugLogger  # noqa: E402
    from scrubber.report import CAVEAT_TEXT  # noqa: E402
    from scrubber.settings import Settings  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(TREE, "tests", "single_instance_driver.py")


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
        self.ini_path = os.path.join(self.tmp.name, "settings.ini")
        qsettings = QSettings(self.ini_path, QSettings.IniFormat)
        self.settings = Settings(qsettings)
        self.logger = DebugLogger(
            "safe-share-scrubber", "0.2.0",
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.windows = []
        self.log = make_text_file(
            os.path.join(self.tmp.name, "debug.log"),
            sample_log_with_secrets())
        self.clean = make_text_file(
            os.path.join(self.tmp.name, "clean.log"),
            sample_innocent_text())

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.logger.uninstall_crash_handler()
        for handler in list(self.logger.logger.handlers):
            handler.close()
            self.logger.logger.removeHandler(handler)
        self.tmp.cleanup()

    def make_window(self):
        window = gui.MainWindow(settings=self.settings,
                                logger=self.logger)
        self.windows.append(window)
        return window

    def test_window_opens_with_default_size(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(1000, 620))

    def test_nothing_selected_by_default(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), -1)
        focused = QApplication.focusWidget()
        self.assertFalse(isinstance(focused, QPushButton))

    def test_click_selects_a_row(self):
        # The auto-select guard must not break real selection: a
        # click on a row selects it.
        window = self.make_window()
        window.show()
        window.add_files([self.log, self.clean])
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), -1)
        rect = window.file_list.visualItemRect(
            window.file_list.item(1))
        QTest.mouseClick(window.file_list.viewport(),
                         Qt.LeftButton, pos=rect.center())
        self.app.processEvents()
        self.assertEqual(window.file_list.currentRow(), 1)

    def test_add_files_adds_a_row(self):
        window = self.make_window()
        window.show()
        added, failures = window.add_files([self.log])
        self.assertEqual((added, failures), (1, []))
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "debug.log")
        self.assertFalse(window.empty_label.isVisible())

    def test_add_files_skips_duplicates(self):
        window = self.make_window()
        window.add_files([self.log, self.log])
        self.assertEqual(window.file_list.count(), 1)

    def test_scrub_writes_safe_copy_and_shows_report(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        original = Path(self.log).read_bytes()
        window.scrub_button.click()
        safe = os.path.join(self.tmp.name, "debug.safe.log")
        self.assertTrue(wait_until(
            lambda: os.path.exists(safe), timeout=15))
        self.assertTrue(wait_until(
            lambda: "Safe to share" in
            window.report_text.toPlainText(), timeout=15))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        self.assertIn("Secrets found: 15",
                      window.report_text.toPlainText())
        self.assertIn("AWS access key: line 2",
                      window.report_text.toPlainText())
        self.assertIn("15 secret(s) redacted",
                      window.status_bar.currentMessage())
        self.assertEqual(window.file_list.item(0).text(),
                         "debug.log: 15 secret(s) redacted")
        self.assertFalse(window.busy_light.property("busy"))
        scrubbed = Path(safe).read_text(encoding="utf-8")
        self.assertNotIn(FAKE_AWS, scrubbed)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe-report.txt")))
        # The original is untouched.
        self.assertEqual(Path(self.log).read_bytes(), original)

    def test_scrub_clean_file_reports_no_secrets(self):
        window = self.make_window()
        window.show()
        window.add_files([self.clean])
        window.scrub_button.click()
        self.assertTrue(wait_until(
            lambda: "Secrets found: 0" in
            window.report_text.toPlainText(), timeout=15))
        self.assertEqual(window.file_list.item(0).text(),
                         "clean.log: no secrets found")

    def test_verify_button_shows_findings_and_writes_nothing(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        original = Path(self.log).read_bytes()
        window.verify_button.click()
        self.assertTrue(wait_until(
            lambda: "Secrets found: 15" in
            window.report_text.toPlainText(), timeout=15))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        text = window.report_text.toPlainText()
        self.assertIn("AWS access key: line 2", text)
        self.assertIn("Verdict: Not safe to share: secrets found",
                      text)
        self.assertIn("Verified 1 file(s): 15 secret(s) found",
                      window.status_bar.currentMessage())
        self.assertEqual(window.file_list.item(0).text(),
                         "debug.log: 15 secret(s) found")
        self.assertFalse(window.busy_light.property("busy"))
        # Verify writes nothing at all.
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe-report.txt")))
        self.assertEqual(Path(self.log).read_bytes(), original)

    def test_verify_clean_file_reports_safe(self):
        window = self.make_window()
        window.show()
        window.add_files([self.clean])
        window.verify_button.click()
        self.assertTrue(wait_until(
            lambda: "Secrets found: 0" in
            window.report_text.toPlainText(), timeout=15))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        self.assertIn("Verdict: Safe to share",
                      window.report_text.toPlainText())
        self.assertEqual(window.file_list.item(0).text(),
                         "clean.log: no secrets found")
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "clean.safe.log")))

    def test_verify_display_has_no_safe_copy_mention(self):
        # Verify writes no safe copy, so its display carries the
        # verify caveat (no safe-copy sentence), matching the CLI.
        from scrubber.cli import VERIFY_CAVEAT
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        window.verify_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
        text = window.report_text.toPlainText()
        self.assertIn(VERIFY_CAVEAT, text)
        self.assertNotIn("safe copy", text)

    def test_verify_from_menu_runs_verify(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        for action in window.menuBar().actions():
            if action.text() == "File":
                for item in action.menu().actions():
                    if item.text() == "Verify":
                        item.trigger()
        self.assertTrue(wait_until(
            lambda: "Secrets found: 15" in
            window.report_text.toPlainText(), timeout=15))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))

    def test_cancel_kills_the_scrub_subprocess(self):
        # A big file keeps the CLI subprocess busy for seconds, so
        # Cancel has a real process to kill. The line is plain
        # prose: no secrets in it.
        line = ("2026-11-14 routine log line with ordinary words "
                "and the number 12345\n")
        big = make_text_file(
            os.path.join(self.tmp.name, "big.log"),
            line * 100000)
        window = self.make_window()
        window.show()
        window.add_files([big])
        window.scrub_button.click()
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
        self.assertIn("Scrub cancelled",
                      window.status_bar.currentMessage())
        # Killed mid-scrub: no safe copy, no report.
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "big.safe.log")))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "big.safe-report.txt")))

    def test_busy_light_is_on_while_scrubbing(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        window.scrub_button.click()
        # The worker starts on the next event loop turn; the busy
        # light is set synchronously in _on_scrub.
        self.assertTrue(window.busy_light.property("busy"))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=15))
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
        self.assertIn(CAVEAT_TEXT, window.caveat_label.text())
        texts = [w.toPlainText()
                 for w in window._how_to_use.findChildren(QWidget)
                 if hasattr(w, "toPlainText")]
        self.assertTrue(any(CAVEAT_TEXT in t for t in texts))

    def test_menus_have_the_actions(self):
        window = self.make_window()
        bar = window.menuBar()
        found = {}
        for action in bar.actions():
            found[action.text()] = [a.text() for a in
                                    action.menu().actions()]
        self.assertIn("Add files", found["File"])
        self.assertIn("Scrub", found["File"])
        self.assertIn("Verify", found["File"])
        self.assertIn("Generate debug report", found["File"])
        self.assertIn("Quit", found["File"])
        self.assertIn("How to Use", found["Help"])

    def test_geometry_memory_round_trips(self):
        # The offscreen platform's screen is 800x800 and
        # restoreGeometry clamps the restored width to it, so the
        # test uses a size that fits the sandbox screen. On his
        # real 1366x768 screen the default 1000x620 fits.
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
        window.add_files([self.log])
        window.scrub_button.click()
        self.assertTrue(wait_until(
            lambda: "Safe to share" in
            window.report_text.toPlainText(), timeout=15))
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "\u2014" in t]
        self.assertEqual(offenders, [])

    def test_no_bare_ampersand_in_visible_labels(self):
        window = self.make_window()
        window.show()
        window.add_files([self.log])
        window.scrub_button.click()
        self.assertTrue(wait_until(
            lambda: "Safe to share" in
            window.report_text.toPlainText(), timeout=15))
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
        mime.setUrls([QUrl.fromLocalFile(self.log)])
        enter = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
        window.dropEvent(drop)
        self.assertEqual(window.file_list.count(), 1)
        self.assertEqual(window.file_list.item(0).text(),
                         "debug.log")

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
        old = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.tmp.name,
                                                    "xdg-cache")
        try:
            first = gui.try_single_instance()
            self.assertIsNotNone(first)
            second = gui.try_single_instance()
            self.assertIsNone(second)
            first.unlock()
        finally:
            if old is None:
                del os.environ["XDG_CACHE_HOME"]
            else:
                os.environ["XDG_CACHE_HOME"] = old

    def test_single_instance_second_launch_exits_zero(self):
        # Two real processes: a driver holds the lock, then a real
        # `python -m scrubber` launch must exit 0 while the first
        # stays alive.
        env = dict(os.environ)
        env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                              "config")
        env["XDG_CACHE_HOME"] = os.path.join(self.tmp.name, "cache")
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
                [sys.executable, "-m", "scrubber"],
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
        return texts


if __name__ == "__main__":
    unittest.main()
