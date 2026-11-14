"""GUI tests (offscreen). Module-guarded: skip cleanly without PySide6."""

import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    from PySide6.QtCore import QPoint, QLockFile, QSettings, QSize, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from helpers import GOOD_DESCRIPTION, FakeOllama, make_image  # noqa: E402

if HAVE_QT:
    from optimizer import core, gui  # noqa: E402
    from optimizer.debug_log import DebugLogger  # noqa: E402
    from optimizer.ollama import OllamaClient  # noqa: E402
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
        self.ini_path = os.path.join(self.tmp.name, "settings.ini")
        qsettings = QSettings(self.ini_path, QSettings.IniFormat)
        self.settings = Settings(qsettings)
        self.cache = core.ImageCache(
            os.path.join(self.tmp.name, "cache"))
        self.logger = DebugLogger(
            "vision-image-optimizer", "0.1.0",
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.servers = []
        self.windows = []
        self.img = make_image(os.path.join(self.tmp.name, "shot.png"),
                              1920, 1080)

    def tearDown(self):
        for window in self.windows:
            window.close()
        for server in self.servers:
            server.stop()
        self.tmp.cleanup()

    def make_window(self, client=None):
        window = gui.MainWindow(settings=self.settings,
                                cache=self.cache,
                                logger=self.logger,
                                ollama_client=client)
        self.windows.append(window)
        return window

    def _server(self, **kwargs):
        server = FakeOllama(**kwargs).start()
        self.servers.append(server)
        return server

    def test_window_opens_with_default_size(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(1100, 650))

    def test_right_pane_fits_without_scrolling(self):
        # Regression: the first build hid the Describe button and
        # the description below the fold at 1100x650. Everything on
        # the right must fit the window with no scroll range.
        window = self.make_window()
        window.show()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        self.app.processEvents()
        scrollbar = window.right_scroll.verticalScrollBar()
        self.assertEqual(scrollbar.maximum(), 0)
        # The description box itself is on screen, not below it.
        bottom = window.description_text.mapTo(window, QPoint(
            0, window.description_text.height())).y()
        self.assertLessEqual(bottom, window.height())

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
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        self.app.processEvents()
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
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        self.app.processEvents()
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
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        self.app.processEvents()
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
        client = OllamaClient(server.base_url)
        window = self.make_window(client=client)
        window.show()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=15))
        self.assertIn("Tokens: 2040 to 144",
                      window.measurements_label.text())
        self.assertIn("minicpm-v",
                      window.measurements_label.text())
        self.assertEqual(len(server.calls), 1)

    def test_describe_second_time_is_cache_hit(self):
        server = self._server()
        client = OllamaClient(server.base_url)
        window = self.make_window(client=client)
        window.show()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=15))
        window.description_text.setPlainText("")
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), timeout=15))
        self.assertIn("from cache",
                      window.measurements_label.text())
        self.assertEqual(len(server.calls), 1)

    def test_cancel_stops_describe(self):
        server = self._server(delay=3.0)
        client = OllamaClient(server.base_url)
        window = self.make_window(client=client)
        window.show()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: window.cancel_button.isEnabled(), timeout=5))
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=10))
        self.assertEqual(window.description_text.toPlainText(), "")
        self.assertTrue(window.describe_button.isEnabled())

    def test_ollama_down_plain_message_and_optimize_still_works(self):
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        client = OllamaClient(url)
        window = self.make_window(client=client)
        window.show()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.describe_button.click()
        self.assertTrue(wait_until(
            lambda: "not running" in
            window.description_text.toPlainText(), timeout=15))
        window.optimize_button.click()
        self.app.processEvents()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out))

    def test_optimize_selected_writes_file(self):
        window = self.make_window()
        window.add_images([self.img])
        window.image_list.setCurrentRow(0)
        window.optimize_button.click()
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out))
        from PIL import Image
        with Image.open(out) as img:
            self.assertEqual(img.size, (512, 288))

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
