"""Kill-picker window tests: offscreen, fake provider and
killer, so no test ever touches a real process.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from preloadchecks import gui
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

GB = 1024 ** 3

PROCESSES = [
    {"pid": 100, "name": "firefox", "rss_mb": 2000.0,
     "cpu_percent": 5.0},
    {"pid": 200, "name": "editor", "rss_mb": 500.0,
     "cpu_percent": 1.0},
]


def make_window(provider=None, killer_fn=None, ram_fn=None,
                require_bytes=None, dry_run=False):
    if provider is None:
        provider = lambda: list(PROCESSES)
    if killer_fn is None:
        killer_fn = lambda pids, confirm, dry_run: []
    if ram_fn is None:
        ram_fn = lambda: (5 * GB, 8 * GB)
    return gui.KillPickerWindow(
        provider=provider, killer_fn=killer_fn, ram_fn=ram_fn,
        require_bytes=require_bytes, dry_run=dry_run)


def tick(window, row):
    item = window.table.item(row, 0)
    item.setCheckState(Qt.CheckState.Checked)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()

    def _open(self, **kwargs):
        window = make_window(**kwargs)
        self.windows.append(window)
        return window

    def test_rows_show_provider_processes(self):
        window = self._open()
        self.assertEqual(window.table.rowCount(), 2)
        self.assertEqual(window.table.item(0, 1).text(),
                         "firefox")
        self.assertEqual(window.table.item(0, 2).text(), "100")
        self.assertEqual(window.table.item(0, 3).text(),
                         "2000 MB")
        self.assertEqual(window.table.item(0, 4).text(), "5%")

    def test_at_most_six_rows(self):
        many = [{"pid": 1000 + i, "name": "proc%d" % i,
                 "rss_mb": 100.0, "cpu_percent": 0.0}
                for i in range(8)]
        window = self._open(provider=lambda: many)
        self.assertEqual(window.table.rowCount(), 6)

    def test_ram_label(self):
        window = self._open()
        self.assertEqual(window.ram_label.text(),
                         "Free RAM: 5.0 GB of 8.0 GB total.")

    def test_fit_label_when_model_fits(self):
        window = self._open(require_bytes=4 * GB)
        self.assertIn("fits in free RAM", window.fit_label.text())

    def test_fit_label_when_model_does_not_fit(self):
        window = self._open(require_bytes=7 * GB)
        self.assertIn("does not fit", window.fit_label.text())
        self.assertIn("short", window.fit_label.text())

    def test_no_fit_label_without_require(self):
        window = self._open()
        self.assertEqual(window.fit_label.text(), "")

    def test_ram_read_failure_is_plain_words(self):
        def broken_ram():
            raise OSError("no meminfo")
        window = self._open(ram_fn=broken_ram)
        self.assertIn("could not read", window.ram_label.text())

    def test_empty_provider_says_nothing_heavy(self):
        window = self._open(provider=lambda: [])
        self.assertEqual(window.table.rowCount(), 0)
        self.assertIn("Nothing heavy is running",
                      window.status_label.text())

    def test_provider_failure_is_plain_words(self):
        def broken():
            raise OSError("no proc")
        window = self._open(provider=broken)
        self.assertIn("Could not list processes",
                      window.status_label.text())

    def test_kill_button_disabled_until_a_box_is_ticked(self):
        window = self._open()
        self.assertFalse(window.kill_button.isEnabled())
        tick(window, 0)
        self.assertTrue(window.kill_button.isEnabled())
        window.table.item(0, 0).setCheckState(
            Qt.CheckState.Unchecked)
        self.assertFalse(window.kill_button.isEnabled())

    def test_kill_stops_only_the_ticked_pids(self):
        calls = []

        def fake_killer(pids, confirm, dry_run):
            calls.append((list(pids), confirm, dry_run))
            return [{"pid": pid, "name": "firefox",
                     "outcome": "stopped", "reason": ""}
                    for pid in pids]

        window = self._open(killer_fn=fake_killer)
        tick(window, 0)  # firefox only, not the editor
        with mock.patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.Yes):
            with mock.patch.object(QMessageBox, "information",
                                   return_value=None):
                window.kill_button.click()
        self.assertEqual(len(calls), 1)
        pids, confirm, dry_run = calls[0]
        self.assertEqual(pids, [100])
        self.assertTrue(confirm)
        self.assertFalse(dry_run)
        self.assertIn("1 process(es) stopped.",
                      window.status_label.text())

    def test_no_at_the_confirmation_stops_nothing(self):
        calls = []

        def fake_killer(pids, confirm, dry_run):
            calls.append(pids)
            return []

        window = self._open(killer_fn=fake_killer)
        tick(window, 0)
        with mock.patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.No):
            with mock.patch.object(QMessageBox, "information",
                                   return_value=None):
                window.kill_button.click()
        self.assertEqual(calls, [])

    def test_dry_run_passes_through(self):
        calls = []

        def fake_killer(pids, confirm, dry_run):
            calls.append((list(pids), confirm, dry_run))
            return [{"pid": pid, "name": "firefox",
                     "outcome": "would stop", "reason": ""}
                    for pid in pids]

        window = self._open(killer_fn=fake_killer, dry_run=True)
        tick(window, 1)
        with mock.patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.Yes):
            with mock.patch.object(QMessageBox, "information",
                                   return_value=None):
                window.kill_button.click()
        self.assertEqual(calls, [([200], True, True)])
        self.assertIn("would be stopped",
                      window.status_label.text())

    def test_refresh_re_reads_the_provider(self):
        state = {"rows": list(PROCESSES)}

        def provider():
            return list(state["rows"])

        window = self._open(provider=provider)
        self.assertEqual(window.table.rowCount(), 2)
        state["rows"] = state["rows"][:1]
        window.refresh_button.click()
        self.assertEqual(window.table.rowCount(), 1)

    def test_refresh_clears_ticks(self):
        window = self._open()
        tick(window, 0)
        self.assertTrue(window.kill_button.isEnabled())
        window.refresh_button.click()
        self.assertFalse(window.kill_button.isEnabled())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class RunGuiTests(unittest.TestCase):
    def test_unknown_option_is_exit_2(self):
        self.assertEqual(gui.run_gui(["--nope"]), 2)

    def test_bad_require_is_exit_2(self):
        self.assertEqual(gui.run_gui(["--require", "banana"]), 2)
        self.assertEqual(gui.run_gui(["--require=banana"]), 2)


if __name__ == "__main__":
    unittest.main()
