"""GUI tests for the thin viewer (offscreen). Module-guarded: skip
cleanly without PySide6.

The window does no shrinking or describing itself: optimize and
describe run the optimizer.shrink / optimizer.describe subprocesses,
and the cache label comes from optimizer.cli cache-stats. The tests
point the window at the fake Ollama server by setting the
ollama_url setting — there is no injected client any more.

Isolation: each test sets XDG_CACHE_HOME and XDG_CONFIG_HOME to its
own temp dir, so the subprocesses (which read their own settings
and cache stores) never touch the real user dirs.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    from PySide6.QtCore import QPoint, QLockFile, QSettings, QSize, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from helpers import GOOD_DESCRIPTION, FakeOllama, make_image  # noqa: E402

if HAVE_QT:
    from optimizer import __version__, gui  # noqa: E402
    from optimizer.debug_log import DebugLogger  # noqa: E402
    from optimizer.settings import Settings  # noqa: E402


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
        # Isolate the subprocesses' settings + cache stores.
        self._old_env = {}
        for key, sub in (("XDG_CACHE_HOME", "xdg-cache"),
                         ("XDG_CONFIG_HOME", "xdg-config")):
            self._old_env[key] = os.environ.get(key)
            os.environ[key] = os.path.join(self.tmp.name, sub)
        self.ini_path = os.path.join(self.tmp.name, "settings.ini")
        qsettings = QSettings(self.ini_path, QSettings.IniFormat)
        self.settings = Settings(qsettings)
        self.logger = DebugLogger(
            "vision-image-optimizer", __version__,
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.servers = []
        self.windows = []
        self.img = make_image(os.path.join(self.tmp.name, "shot.png"),
                              1920, 1080)
        self.img2 = make_image(os.path.join(self.tmp.name,
                                            "shot2.png"),
                               800, 600)

    def tearDown(self):
        for window in self.windows:
            window.close()
        for server in self.servers:
            server.stop()
        for key, old in self._old_env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self.tmp.cleanup()

    def make_window(self):
        window = gui.MainWindow(settings=self.settings,
                                logger=self.logger)
        self.windows.append(window)
        return window

    def _server(self, **kwargs):
        """Start a fake Ollama server and point the settings at it."""
        server = FakeOllama(**kwargs).start()
        self.servers.append(server)
        self.settings.set("ollama_url", server.base_url)
        return server

    def _add_and_select(self, window, image=None):
        window.add_images([image or self.img])
        window.image_list.setCurrentRow(0)
        self.app.processEvents()

    def test_window_opens_with_default_size(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(1100, 650))

    def test_right_pane_fits_without_scrolling(self):
        # Regression: the first build hid the Describe button and
        # the description below the fold at 1100x650. Everything on
        # the right must fit the window with no scroll range — empty,
        # with an image added, and with a description shown.
        window = self.make_window()
        window.show()
        self.app.processEvents()
        scrollbar = window.right_scroll.verticalScrollBar()
        self.assertEqual(scrollbar.maximum(), 0)
        self._add_and_select(window)
        self.assertEqual(scrollbar.maximum(), 0)
        # The description box itself is on screen, not below it.
        bottom = window.description_text.mapTo(window, QPoint(
            0, window.description_text.height())).y()
        self.assertLessEqual(bottom, window.height())
        # Described state: a long description plus the two-line
        # measurements text must still leave zero scroll range.
        window.description_text.setPlainText(GOOD_DESCRIPTION)
        window.measurements_label.setText(
            "Model: minicpm-v  Fast look: 0.00 s  Tokens: 2040 to 144"
            "  Size: 9.8 KB to 19.2 KB  (from cache)")
        self.app.processEvents()
        self.assertEqual(scrollbar.maximum(), 0)

    def test_measurements_label_fits_two_lines(self):
        # Regression: a cache hit appends "  (from cache)", the
        # measurements text wraps to two lines, and the label stayed
        # one line tall (probed: 17 px against a 34 px size hint),
        # so the second line rendered half-cut.
        window = self.make_window()
        window.show()
        window.measurements_label.setText(
            "Model: minicpm-v  Fast look: 0.00 s  Tokens: 2040 to 144"
            "  Size: 9.8 KB to 19.2 KB  (from cache)")
        self.app.processEvents()
        label = window.measurements_label
        two_lines = 2 * label.fontMetrics().lineSpacing()
        self.assertGreaterEqual(label.height(), two_lines)
        self.assertEqual(
            window.right_scroll.verticalScrollBar().maximum(), 0)

    def test_empty_states_present(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.empty_label.isVisible())
        self.assertIn("Drop images here",
                      window.preview.text())
        self.assertEqual(window.image_list.count(), 0)
        self.assertEqual(window.token_label.text(),
                         "No image selected")

    def test_nothing_selected_by_default(self):
        window = self.make_window()
        window.add_images([self.img])
        self.assertEqual(window.image_list.currentRow(), -1)

    def test_add_image_shows_tokens_before_and_after(self):
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        self.assertIn("2040", window.token_label.text())
        self.assertIn("144", window.token_label.text())
        self.assertIn("2040 to 144",
                      window.image_list.item(0).text())
        self.assertIn("2040 tokens to 144 tokens",
                      window.totals_label.text())

    def test_resize_preset_changes_estimate(self):
        window = self.make_window()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.size_preset.setCurrentText("1024w")
        self.app.processEvents()
        # 1024x576 -> 32 * 18 = 576 tokens.
        self.assertIn("576", window.token_label.text())
        window.size_preset.setCurrentText("Original")
        self.app.processEvents()
        self.assertIn("2040 to 2040", window.token_label.text())

    def test_crop_spin_boxes_change_estimate_and_preview(self):
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.crop_w.setValue(960)
        self.app.processEvents()
        # Crop 960x1080 -> resize 512w -> 512x576 -> 16*18 = 288.
        self.assertIn("288", window.token_label.text())
        self.assertEqual(window.preview.crop(), (0, 0, 960, 1080))
        window.full_image_button.click()
        self.app.processEvents()
        self.assertIsNone(window.preview.crop())
        self.assertIn("144", window.token_label.text())

    def test_rubber_band_crop_sets_spin_boxes(self):
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        preview = window.preview
        rect = preview._display_rect_for()
        self.assertGreater(rect.width(), 100)
        start = rect.topLeft() + QPoint(10, 10)
        end = rect.center()
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(preview, pos=end)
        QTest.mouseRelease(preview, Qt.LeftButton, pos=end)
        self.app.processEvents()
        crop = preview.crop()
        self.assertIsNotNone(crop)
        self.assertGreater(crop[2], 0)
        self.assertGreater(crop[3], 0)
        self.assertEqual(window.crop_w.value(), crop[2])
        self.assertEqual(window.crop_h.value(), crop[3])

    def test_describe_against_fake_server(self):
        server = self._server()
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=20))
        self.assertIn("Tokens: 2040 to 144",
                      window.measurements_label.text())
        self.assertIn("minicpm-v",
                      window.measurements_label.text())
        self.assertEqual(len(server.calls), 1)
        # Describe saves the shrunken copy first, then describes it.
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out), out)

    def test_describe_second_time_is_cache_hit(self):
        server = self._server()
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=20))
        window.description_text.setPlainText("")
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=20))
        self.assertIn("from cache",
                      window.measurements_label.text())
        self.assertEqual(len(server.calls), 1)

    def test_cancel_stops_describe(self):
        server = self._server(delay=3.0)
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: window.cancel_button.isEnabled(), timeout=5))
        # Let the shrink step finish so the cancel lands mid-describe.
        time.sleep(1.0)
        self.app.processEvents()
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=10))
        self.assertEqual(window.description_text.toPlainText(), "")
        self.assertTrue(window.describe_button.isEnabled())
        self.assertFalse(window.busy_light.property("busy"))

    def test_ollama_down_plain_message_and_optimize_still_works(self):
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        self.settings.set("ollama_url", url)
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: "not running" in
            window.description_text.toPlainText(), timeout=20))
        window.optimize_button.click()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(wait_until(lambda: os.path.exists(out),
                                   timeout=15))

    def test_optimize_selected_writes_file(self):
        window = self.make_window()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.optimize_button.click()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(wait_until(lambda: os.path.exists(out),
                                   timeout=15))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=10))
        from PIL import Image
        with Image.open(out) as img:
            self.assertEqual(img.size, (512, 288))

    def test_optimize_all_writes_each_file(self):
        window = self.make_window()
        window.add_images([self.img, self.img2])
        window.optimize_all_button.click()
        out1 = os.path.join(self.tmp.name, "optimized",
                            "shot-512w.jpg")
        out2 = os.path.join(self.tmp.name, "optimized",
                            "shot2-512w.jpg")
        self.assertTrue(wait_until(
            lambda: os.path.exists(out1) and os.path.exists(out2),
            timeout=20))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=10))

    def test_cache_label_updates_from_subprocess(self):
        # The label starts empty (or "unavailable" while the first
        # stats call is in flight) and shows the real counts once
        # an optimize has filled the cache.
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.optimize_button.click()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(wait_until(lambda: os.path.exists(out),
                                   timeout=15))
        self.assertTrue(wait_until(
            lambda: "1 optimized picture(s)" in
            window.cache_label.text(), timeout=15),
            window.cache_label.text())

    def test_clear_cache_empties_cache(self):
        window = self.make_window()
        window.show()
        self._add_and_select(window)
        window.optimize_button.click()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(wait_until(lambda: os.path.exists(out),
                                   timeout=15))
        self.assertTrue(wait_until(
            lambda: "1 optimized picture(s)" in
            window.cache_label.text(), timeout=15))
        with mock.patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.Yes):
            window.clear_cache_button.click()
        self.assertTrue(wait_until(
            lambda: "0 optimized picture(s)" in
            window.cache_label.text(), timeout=15),
            window.cache_label.text())

    def test_geometry_memory_round_trips(self):
        # The offscreen platform's screen is 800x800 and
        # restoreGeometry clamps the restored width to it (probed:
        # a bare window restores 1000x700 as 798x700), so the test
        # uses a size that fits the sandbox screen. On his real
        # 1366x768 screen the default 1100x650 fits and round-trips.
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

    def test_how_to_use_window_opens(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        self.assertIsNotNone(window._how_to_use)
        self.assertTrue(window._how_to_use.isVisible())
        self.assertIn("How to Use",
                      window._how_to_use.windowTitle())
        # The chain is documented in the How to Use text.
        self.assertIn("vision-shrink", gui.HOW_TO_USE_TEXT)
        self.assertIn("vision-describe", gui.HOW_TO_USE_TEXT)

    def test_no_em_dash_in_visible_text(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "\u2014" in t]
        self.assertEqual(offenders, [])

    def test_no_bare_ampersand_in_visible_labels(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "&" in t]
        self.assertEqual(offenders, [])

    def test_caveat_is_visible(self):
        window = self.make_window()
        self.assertIn("does not get 14x faster",
                      window.caveat_label.text())

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

    # -- helpers ------------------------------------------------------
    def _collect_visible_text(self, root):
        texts = []
        for widget in [root] + root.findChildren(QWidget):
            for getter in ("text", "windowTitle", "placeholderText",
                           "toolTip", "title", "currentText"):
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
