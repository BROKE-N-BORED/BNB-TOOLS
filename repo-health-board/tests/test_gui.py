"""GUI tests (offscreen). Module-guarded: skip cleanly without PySide6.

Display tests use fixture flagged.json files (no network, no
subprocess). Refresh tests run the real chain against the fake
GitHub server from helpers. Chain tests skip cleanly when
board.fetch / board.flag are not importable yet.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtCore import QLockFile, QSettings, QSize, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QMessageBox,
                                   QPushButton, QWidget)
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from helpers import (iso_days_ago, make_default_fixtures,  # noqa: E402
                     make_many_repos_fixtures,
                     make_rate_limit_fixtures, start_fake_github,
                     stop_fake_github)

if HAVE_QT:
    from board import gui  # noqa: E402
    from board.debug_log import DebugLogger  # noqa: E402
    from board.settings import Settings, data_dir  # noqa: E402

try:
    import board.fetch  # noqa: F401
    import board.flag  # noqa: F401
    HAVE_CHAIN = True
except ImportError:
    HAVE_CHAIN = False

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


def make_flagged_board(rows, org="TEST-ORG", rate_limited=False,
                       rate_reset_at=None):
    """A flagged.json dict in the contract shape."""
    flagged = 0
    unchecked = 0
    for row in rows:
        if row["flags"]:
            flagged += 1
        if row["health"].get("file_count") is None:
            unchecked += 1
    return {
        "org": org,
        "fetched_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "rate_limited": rate_limited,
        "rate_reset_at": rate_reset_at,
        "rows": rows,
        "counts": {"total": len(rows), "flagged": flagged,
                   "unchecked": unchecked},
    }


def make_row(name, days_ago=None, files=7, release="v1.0.0",
             suite="has CI", flags=(), org="TEST-ORG"):
    """One flagged row. days_ago None means an unknown commit date."""
    return {
        "health": {
            "name": name,
            "html_url": "https://github.com/%s/%s" % (org, name),
            "description": "Test repo %s." % name,
            "topics": ["test"],
            "pushed_at": iso_days_ago(1),
            "last_commit_date": (iso_days_ago(days_ago)
                                 if days_ago is not None else None),
            "last_commit_sha": "a" * 40,
            "file_count": files,
            "tree_paths": ["README.md"],
            "latest_release_tag": release,
            "fetched_at": iso_days_ago(0),
            "from_cache": False,
        },
        "flags": [{"kind": kind, "label": label}
                  for kind, label in flags],
        "suite": suite,
    }


def fixture_rows():
    """Four rows with distinct dates and flag counts, for sort
    tests: aurora (2 days, 0 flags), bare-bones (3 days, 2 flags),
    stale-widget (200 days, 1 flag), empty-shell (unknown date,
    5 flags)."""
    return [
        make_row("aurora", days_ago=2, release="v1.2.0"),
        make_row("bare-bones", days_ago=3, release=None,
                 suite="no CI file",
                 flags=(("missing-description", "no description"),
                        ("missing-topics", "no topics"))),
        make_row("stale-widget", days_ago=200, release="v0.9.1",
                 flags=(("stale", "stale (no commit in 90 days)"),)),
        make_row("empty-shell", days_ago=None, files=0,
                 release=None, suite="no CI file",
                 flags=(("placeholder", "placeholder"),
                        ("missing-readme", "no README"),
                        ("missing-license", "no LICENSE"),
                        ("missing-gitignore", "no .gitignore"),
                        ("missing-security", "no SECURITY.md"))),
    ]


class BlackholeServer:
    """A server that accepts connections and never answers: the
    fetch hangs in its request until the subprocess is killed,
    which is what the Cancel test needs."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET,
                                  socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET,
                             socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve,
                                        daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.sock.getsockname()[1]

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            # Hold the connection open without answering.
            threading.Thread(target=self._hold, args=(conn,),
                             daemon=True).start()

    def _hold(self, conn):
        try:
            while not self._stop.is_set():
                time.sleep(0.1)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(timeout=5)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(gui.DARK_STYLESHEET)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_xdg_data = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp.name,
                                                   "data")
        self._old_base_url = os.environ.get("BOARD_BASE_URL")
        os.environ.pop("BOARD_BASE_URL", None)
        self.ini_path = os.path.join(self.tmp.name, "settings.ini")
        self.qsettings = QSettings(self.ini_path,
                                   QSettings.IniFormat)
        self.settings = Settings()
        self.logger = DebugLogger(
            "repo-health-board", "0.1.0",
            log_dir=os.path.join(self.tmp.name, "logs"))
        self.windows = []
        self.servers = []
        self.blackhole = None

    def tearDown(self):
        for window in self.windows:
            if window._worker is not None:
                window._worker.cancel()
                window._worker.wait(3000)
            window.close()
        self.app.processEvents()
        self.logger.uninstall_crash_handler()
        for handler in list(self.logger.logger.handlers):
            handler.close()
            self.logger.logger.removeHandler(handler)
        for server in self.servers:
            stop_fake_github(server)
        if self.blackhole is not None:
            self.blackhole.stop()
        if self._old_xdg_data is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg_data
        if self._old_base_url is None:
            os.environ.pop("BOARD_BASE_URL", None)
        else:
            os.environ["BOARD_BASE_URL"] = self._old_base_url
        self.tmp.cleanup()

    # -- helpers ------------------------------------------------------
    def make_window(self, chain_env=None, logger=None):
        window = gui.MainWindow(settings=self.settings,
                                logger=logger or self.logger,
                                qsettings=self.qsettings,
                                chain_env=chain_env)
        self.windows.append(window)
        return window

    def write_flagged(self, board):
        path = os.path.join(data_dir(), "flagged.json")
        os.makedirs(data_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(board, fh)
        return path

    def write_board_text(self, text):
        path = os.path.join(data_dir(), "board.txt")
        os.makedirs(data_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def row_names(self, window):
        return [window.table.item(row, gui.COL_REPO).text()
                for row in range(window.table.rowCount())]

    def click_header(self, window, column):
        header = window.table.horizontalHeader()
        pos = header.sectionViewportPosition(column)
        size = header.sectionSize(column)
        # Click the section centre in viewport coordinates.
        from PySide6.QtCore import QPoint
        center = QPoint(pos + size // 2, header.height() // 2)
        QTest.mouseClick(header.viewport(), Qt.LeftButton,
                         pos=center)
        self.app.processEvents()

    def start_server(self, fixtures):
        server, base_url = start_fake_github(fixtures)
        self.servers.append(server)
        return base_url

    # -- display ------------------------------------------------------
    def test_window_opens_at_default_size_showing_fixture_board(
            self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size(), QSize(1100, 650))
        self.assertEqual(window.table.rowCount(), 4)
        self.assertEqual(self.row_names(window),
                         ["aurora", "bare-bones", "empty-shell",
                          "stale-widget"])
        status = window.status_bar.currentMessage()
        self.assertIn("TEST-ORG", status)
        self.assertIn("4 repos", status)
        self.assertIn("3 flagged", status)
        self.assertFalse(window.empty_label.isVisible())

    def test_no_board_yet_shows_plain_message(self):
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.table.rowCount(), 0)
        self.assertTrue(window.empty_label.isVisible())
        self.assertEqual(window.empty_label.text(),
                         gui.EMPTY_BOARD_MESSAGE)
        self.assertIn("No board yet",
                      window.status_bar.currentMessage())

    def test_corrupt_flagged_json_shows_plain_message(self):
        path = os.path.join(data_dir(), "flagged.json")
        os.makedirs(data_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.table.rowCount(), 0)
        self.assertTrue(window.empty_label.isVisible())

    def test_sort_by_last_commit_unknown_dates_last(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.click_header(window, gui.COL_COMMIT)
        # Ascending: oldest first, unknown last.
        self.assertEqual(self.row_names(window),
                         ["stale-widget", "bare-bones", "aurora",
                          "empty-shell"])
        self.click_header(window, gui.COL_COMMIT)
        # Descending: newest first, unknown still last.
        self.assertEqual(self.row_names(window),
                         ["aurora", "bare-bones", "stale-widget",
                          "empty-shell"])

    def test_sort_by_flag_count(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.click_header(window, gui.COL_FLAGS)
        self.assertEqual(self.row_names(window),
                         ["aurora", "stale-widget", "bare-bones",
                          "empty-shell"])
        self.click_header(window, gui.COL_FLAGS)
        self.assertEqual(self.row_names(window),
                         ["empty-shell", "bare-bones",
                          "stale-widget", "aurora"])

    def test_sort_by_name(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        # Default sort is name ascending.
        self.assertEqual(self.row_names(window),
                         ["aurora", "bare-bones", "empty-shell",
                          "stale-widget"])
        self.click_header(window, gui.COL_REPO)
        self.assertEqual(self.row_names(window),
                         ["stale-widget", "empty-shell",
                          "bare-bones", "aurora"])

    def test_click_repo_name_opens_url(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        opened = []
        with mock.patch.object(
                gui.QDesktopServices, "openUrl",
                side_effect=lambda url: opened.append(
                    url.toString())):
            rect = window.table.visualItemRect(
                window.table.item(0, gui.COL_REPO))
            QTest.mouseClick(window.table.viewport(),
                             Qt.LeftButton, pos=rect.center())
            self.app.processEvents()
        self.assertEqual(opened, ["https://github.com/TEST-ORG/"
                                  "aurora"])

    def test_click_other_column_opens_nothing(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        opened = []
        with mock.patch.object(
                gui.QDesktopServices, "openUrl",
                side_effect=lambda url: opened.append(
                    url.toString())):
            rect = window.table.visualItemRect(
                window.table.item(0, gui.COL_FILES))
            QTest.mouseClick(window.table.viewport(),
                             Qt.LeftButton, pos=rect.center())
            self.app.processEvents()
        self.assertEqual(opened, [])

    def test_nothing_selected_by_default(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        # Let any auto-select Qt does on a later loop turn fire.
        self.assertTrue(wait_until(
            lambda: QApplication.focusWidget() is not None,
            timeout=5))
        time.sleep(0.3)
        self.app.processEvents()
        self.assertEqual(window.table.currentRow(), -1)
        self.assertEqual(window.table.selectedItems(), [])
        focused = QApplication.focusWidget()
        self.assertFalse(isinstance(focused, QPushButton))

    def test_click_selects_a_row(self):
        # The auto-select guard must not break real selection: a
        # click on a row selects it.
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.table.currentRow(), -1)
        rect = window.table.visualItemRect(
            window.table.item(1, gui.COL_FILES))
        QTest.mouseClick(window.table.viewport(), Qt.LeftButton,
                         pos=rect.center())
        self.app.processEvents()
        self.assertEqual(window.table.currentRow(), 1)

    # -- menus, how to use, export ------------------------------------
    def test_menus_have_the_actions(self):
        window = self.make_window()
        bar = window.menuBar()
        found = {}
        for action in bar.actions():
            found[action.text()] = [a.text() for a in
                                    action.menu().actions()]
        self.assertIn("Export board", found["File"])
        self.assertIn("Generate debug report", found["File"])
        self.assertIn("Quit", found["File"])
        self.assertIn("How to Use", found["Help"])

    def test_how_to_use_window_opens(self):
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        self.assertIsNotNone(window._how_to_use)
        self.assertTrue(window._how_to_use.isVisible())
        self.assertIn("How to Use",
                      window._how_to_use.windowTitle())
        texts = [w.toPlainText()
                 for w in window._how_to_use.findChildren(QWidget)
                 if hasattr(w, "toPlainText")]
        body = "\n".join(texts)
        self.assertIn("60", body)
        self.assertIn("placeholder", body)
        self.assertIn("board.fetch", body)
        self.assertIn("board.flag", body)
        self.assertIn("never says whether CI passes", body)

    def test_export_writes_board_txt_when_present(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        self.write_board_text("BOARD TEXT\n")
        window = self.make_window()
        window.show()
        out = os.path.join(self.tmp.name, "exported.txt")
        with mock.patch(
                "board.gui.QFileDialog.getSaveFileName",
                return_value=(out, "")):
            window._on_export()
        self.assertEqual(Path(out).read_text(encoding="utf-8"),
                         "BOARD TEXT\n")
        self.assertIn("exported to",
                      window.status_bar.currentMessage())

    def test_export_builds_text_from_rows_when_board_txt_missing(
            self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        out = os.path.join(self.tmp.name, "exported.txt")
        with mock.patch(
                "board.gui.QFileDialog.getSaveFileName",
                return_value=(out, "")):
            window._on_export()
        text = Path(out).read_text(encoding="utf-8")
        self.assertIn("Repo Health Board: TEST-ORG", text)
        self.assertIn("aurora | ", text)
        self.assertIn("4 repos, 3 flagged, 1 ok", text)

    def test_debug_report_writes_file(self):
        # The wired logger (gui.make_logger), not the bare test
        # logger: the report must carry the GitHub API service
        # check. BOARD_BASE_URL points the check at the fake
        # server so the test never touches the live API.
        base_url = self.start_server(make_default_fixtures())
        os.environ["BOARD_BASE_URL"] = base_url
        logger = gui.make_logger()
        self.addCleanup(logger.uninstall_crash_handler)
        window = self.make_window(logger=logger)
        window.show()
        shown = []
        with mock.patch.object(
                QMessageBox, "information",
                side_effect=lambda *args: shown.append(args)):
            window._on_debug_report()
        self.assertEqual(len(shown), 1)
        log_dir = os.path.join(data_dir(), "logs")
        reports = [name for name in os.listdir(log_dir)
                   if name.startswith("debug-report-")]
        self.assertEqual(len(reports), 1)
        text = Path(os.path.join(log_dir, reports[0])).read_text(
            encoding="utf-8")
        self.assertIn("GitHub API", text)
        self.assertIn("reachable (HTTP 200)", text)
        self.assertIn("repo-health-board", text)
        self.assertIn("Debug report written to",
                      window.status_bar.currentMessage())

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
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "\u2014" in t]
        self.assertEqual(offenders, [])

    def test_no_bare_ampersand_in_visible_labels(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        window._on_how_to_use()
        self.app.processEvents()
        texts = self._collect_visible_text(window)
        texts += self._collect_visible_text(window._how_to_use)
        offenders = [t for t in texts if "&" in t]
        self.assertEqual(offenders, [])

    def _collect_visible_text(self, root):
        texts = []
        for widget in [root] + root.findChildren(QWidget):
            for getter in ("text", "windowTitle",
                           "placeholderText", "toolTip", "title",
                           "currentText", "toPlainText"):
                func = getattr(widget, getter, None)
                if callable(func):
                    try:
                        value = func()
                    except Exception:
                        continue
                    if isinstance(value, str) and value:
                        texts.append(value)
        from PySide6.QtGui import QAction
        for action in root.findChildren(QAction):
            if action.text():
                texts.append(action.text())
        if hasattr(root, "status_bar"):
            texts.append(root.status_bar.currentMessage())
        return texts

    # -- refresh outcomes without the chain ---------------------------
    def test_rate_limit_message_names_reset_time(self):
        reset = int((datetime.now(timezone.utc)
                     + timedelta(hours=1)).timestamp())
        self.write_flagged(make_flagged_board(
            fixture_rows(), rate_limited=True,
            rate_reset_at=reset))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        window._on_refresh_finished(1, 0)
        self.app.processEvents()
        status = window.status_bar.currentMessage()
        self.assertIn("60", status)
        self.assertIn("last good one", status)
        self.assertIn("today at", status)
        self.assertIsNotNone(window._rate_notice)
        self.assertTrue(window._rate_notice.isVisible())
        self.assertIn("last good one",
                      window._rate_notice.text())
        # The cached rows stay on screen.
        self.assertEqual(window.table.rowCount(), 4)

    def test_fetch_failure_keeps_board(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        window._on_refresh_finished(2, -1)
        self.assertIn("unchanged",
                      window.status_bar.currentMessage())
        self.assertEqual(window.table.rowCount(), 4)

    def test_partial_fetch_without_rate_limit_says_so(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        window = self.make_window()
        window.show()
        self.app.processEvents()
        window._on_refresh_finished(1, 0)
        self.assertIn("Some repos could not be checked",
                      window.status_bar.currentMessage())
        self.assertIsNone(window._rate_notice)

    # -- refresh against the fake server ------------------------------
    @unittest.skipUnless(HAVE_CHAIN,
                         "board.fetch / board.flag not built yet")
    def test_refresh_runs_chain_against_fake_server(self):
        base_url = self.start_server(make_default_fixtures())
        window = self.make_window(
            chain_env={"BOARD_BASE_URL": base_url})
        window.show()
        self.app.processEvents()
        self.assertEqual(window.table.rowCount(), 0)
        window.refresh_button.click()
        self.assertFalse(window.refresh_button.isEnabled())
        self.assertTrue(window.cancel_button.isEnabled())
        self.assertTrue(wait_until(
            lambda: window.table.rowCount() == 7, timeout=60))
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=60))
        self.assertIn("aurora", self.row_names(window))
        self.assertIn("Board updated",
                      window.status_bar.currentMessage())
        self.assertTrue(os.path.exists(
            os.path.join(data_dir(), "flagged.json")))
        self.assertTrue(os.path.exists(
            os.path.join(data_dir(), "board.txt")))
        self.assertTrue(window.refresh_button.isEnabled())
        self.assertFalse(window.cancel_button.isEnabled())

    @unittest.skipUnless(HAVE_CHAIN,
                         "board.fetch / board.flag not built yet")
    def test_refresh_progress_shows_checking_lines(self):
        base_url = self.start_server(
            make_many_repos_fixtures(30))
        window = self.make_window(
            chain_env={"BOARD_BASE_URL": base_url})
        window.show()
        window.refresh_button.click()
        seen = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self.app.processEvents()
            message = window.status_bar.currentMessage()
            # A "Checking N of M: name" progress line, not the
            # initial "Checking <org>..." status.
            if message.startswith("Checking ") and " of " in message:
                seen.append(message)
                break
            if window._worker is None:
                break
            time.sleep(0.05)
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=60))
        self.assertTrue(seen, "no Checking progress line seen")
        self.assertIn("of 30", seen[0])

    @unittest.skipUnless(HAVE_CHAIN,
                         "board.fetch / board.flag not built yet")
    def test_rate_limit_refresh_shows_plain_message(self):
        base_url = self.start_server(make_rate_limit_fixtures())
        window = self.make_window(
            chain_env={"BOARD_BASE_URL": base_url})
        window.show()
        window.refresh_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=60))
        self.app.processEvents()
        status = window.status_bar.currentMessage()
        self.assertIn("60", status)
        self.assertIn("last good one", status)
        self.assertIsNotNone(window._rate_notice)
        self.assertTrue(window._rate_notice.isVisible())
        # The partial board still shows: every listed repo is on
        # screen, the uncheckable ones marked unknown.
        self.assertEqual(window.table.rowCount(), 7)

    @unittest.skipUnless(HAVE_CHAIN,
                         "board.fetch / board.flag not built yet")
    def test_cancel_stops_slow_refresh(self):
        self.write_flagged(make_flagged_board(fixture_rows()))
        self.blackhole = BlackholeServer()
        self.blackhole.start()
        window = self.make_window(
            chain_env={"BOARD_BASE_URL": self.blackhole.url})
        window.show()
        self.app.processEvents()
        self.assertEqual(window.table.rowCount(), 4)
        window.refresh_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is not None, timeout=10))
        time.sleep(1.0)
        self.app.processEvents()
        self.assertTrue(window.cancel_button.isEnabled())
        window.cancel_button.click()
        self.assertTrue(wait_until(
            lambda: window._worker is None, timeout=30))
        self.assertIn("cancelled",
                      window.status_bar.currentMessage())
        self.assertTrue(window.refresh_button.isEnabled())
        self.assertFalse(window.cancel_button.isEnabled())
        # The board on screen is unchanged.
        self.assertEqual(window.table.rowCount(), 4)
        self.assertEqual(self.row_names(window),
                         ["aurora", "bare-bones", "empty-shell",
                          "stale-widget"])

    # -- single instance ----------------------------------------------
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
        first = gui.try_single_instance()
        self.assertIsNotNone(first)
        second = gui.try_single_instance()
        self.assertIsNone(second)
        first.unlock()

    def test_single_instance_second_launch_exits_zero(self):
        # Two real processes: a driver holds the lock, then a real
        # `python -m board.gui_main` launch must exit 0 while the
        # first stays alive.
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = os.path.join(self.tmp.name, "data")
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
                            "driver never took the lock")
            self.assertIsNone(driver.poll())
            second = subprocess.run(
                [sys.executable, "-m", "board.gui_main"],
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


if __name__ == "__main__":
    unittest.main()
