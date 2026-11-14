"""Qt GUI for Repo Health Board: a THIN viewer.

This window only displays a flagged JSON board. It does no
fetching and no flagging itself: Refresh runs the chain pieces
(board.fetch, then board.flag) as subprocesses in a worker
thread, then reloads flagged.json from the data dir.

Hard rule: this module must NOT import board.api, board.flags,
board.refresh, board.cache, board.export, or board.cli. It may
import board.settings, board.debug_log, the standard library,
and Qt. tests/test_packaging.py greps the imports and fails the
suite if a banned import appears.

Visible text rules (design rules U11, U33): no em-dashes
anywhere, no bare & in any label. Keep it that way when editing
strings.
"""

import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

from PySide6.QtCore import QByteArray, QEvent, QLockFile, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont,
                          QKeySequence)
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPushButton,
                               QStatusBar, QTableWidget,
                               QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from . import __version__
from .debug_log import DebugLogger
from .settings import (DEFAULT_ORG, Settings, data_dir,
                       default_board_text_path,
                       default_flagged_path, log_dir)

APP_DISPLAY_NAME = "Repo Health Board"
APP_SLUG = "repo-health-board"
REPORT_EMAIL = "broke.n.bored.studio@gmail.com"
DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 650
TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COL_REPO = 0
COL_COMMIT = 1
COL_FILES = 2
COL_RELEASE = 3
COL_SUITE = 4
COL_FLAGS = 5
COLUMNS = ("Repo", "Last commit", "Files", "Release", "Suite",
           "Flags")
EMPTY_BOARD_MESSAGE = "No board yet. Press Refresh to build one."

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #23262b; color: #e8e8e8;
    font-size: 13px; }
QPushButton { background-color: #33373d; border: 1px solid #4a4f56;
    border-radius: 5px; padding: 4px 12px; color: #e8e8e8; }
QPushButton:hover { background-color: #3d4249; }
QPushButton:pressed { background-color: #2b2e33; }
QPushButton:disabled { color: #777777; }
QPushButton:focus, QTableWidget:focus, QTextEdit:focus,
QLineEdit:focus { border: 2px solid #e8a33d; outline: none; }
QPushButton#refreshButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#refreshButton:hover { background-color: #a06f22; }
QPushButton#refreshButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QLineEdit { background-color: #1a1d21; border: 1px solid #3a3e44;
    border-radius: 4px; padding: 4px; color: #e8e8e8; }
QTableWidget { background-color: #1a1d21; border: 1px solid #3a3e44;
    border-radius: 4px; gridline-color: #3a3e44; color: #e8e8e8;
    selection-background-color: #3d4249; }
QHeaderView::section { background-color: #33373d; color: #e8e8e8;
    border: 1px solid #4a4f56; padding: 4px; }
QTextEdit { background-color: #1a1d21; border: 1px solid #3a3e44;
    border-radius: 4px; padding: 3px; color: #e8e8e8; }
QLabel#emptyStateLabel { color: #b0b0b0; font-style: italic; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
"""


def lock_file_path():
    return os.path.join(data_dir(), "single-instance.lock")


def try_single_instance():
    """Hold the single-instance lock. Returns the QLockFile, or None
    when another copy already holds it. A stale lock left by a
    crash is taken over: QLockFile drops a lock whose owning
    process is gone."""
    os.makedirs(data_dir(), exist_ok=True)
    lock = QLockFile(lock_file_path())
    lock.setStaleLockTime(0)
    # This PySide6 build requires the timeout argument.
    if lock.tryLock(0):
        return lock
    return None


def _github_status():
    """GitHub API status for the debug report (short timeout, so a
    dead network never stalls the report). BOARD_BASE_URL is
    honored so tests can point it at the fake server."""
    base = os.environ.get("BOARD_BASE_URL") or "https://api.github.com"
    try:
        with urllib.request.urlopen(base + "/rate_limit",
                                    timeout=2) as resp:
            return "reachable (HTTP %s)" % resp.status
    except urllib.error.HTTPError as exc:
        return "reachable but errored (HTTP %s)" % exc.code
    except Exception as exc:
        return "not reachable (%s)" % exc


def make_logger():
    """The debug log layer, wired to this app.

    Settings: the app version and the org, no secrets ever.
    Services: the GitHub API, the one service the app depends on.
    """
    logger = DebugLogger(APP_SLUG, __version__, log_dir=log_dir())
    logger.register_dependency("PySide6")
    logger.set_setting("app_version", __version__)
    logger.set_setting("org", Settings().org)
    logger.register_service("GitHub API", _github_status)
    return logger


def load_flagged_board(path=None):
    """The flagged board dict, or None when the file is missing,
    unreadable, or the wrong shape. Never raises: a missing board
    is an empty table, not a crash."""
    import json
    path = path or default_flagged_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(
            data.get("rows"), list):
        return None
    return data


def parse_iso_date(value):
    """A GitHub ISO date to a naive local datetime, or None."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def plain_reset_time(epoch):
    """A rate-limit reset epoch in plain words: "today at 3:20 PM",
    "tomorrow at 9:05 AM", or a weekday date. Falls back to "in
    about an hour" when the epoch is missing or unusable."""
    if not epoch:
        return "in about an hour"
    try:
        when = datetime.fromtimestamp(epoch)
    except (TypeError, ValueError, OverflowError, OSError):
        return "in about an hour"
    now = datetime.now()
    clock = when.strftime("%I:%M %p").lstrip("0")
    if when <= now:
        return "now"
    if when.date() == now.date():
        return "today at %s" % clock
    if (when.date() - now.date()).days == 1:
        return "tomorrow at %s" % clock
    return when.strftime("%A, %B %d at ") + clock


def format_fetched_at(value):
    """A fetched_at ISO stamp for the status bar, or "unknown"."""
    parsed = parse_iso_date(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y-%m-%d %H:%M")


class RefreshWorker(QThread):
    """Run the fetch + flag chain as subprocesses, off the UI
    thread. The window stays responsive, progress lines show in
    the status bar, and Cancel terminates the running subprocess.

    Signals: progress(str) for each stdout line, finished(int,
    int) with (fetch exit code, flag exit code; flag is -1 when
    fetch could not run at all), cancelled() when Cancel stopped
    the chain.
    """

    progress = Signal(str)
    finished = Signal(int, int)
    cancelled = Signal()

    def __init__(self, org, chain_env=None, parent=None):
        super().__init__(parent)
        self._org = org
        self._chain_env = dict(chain_env or {})
        self._cancel_requested = False
        self._proc = None

    def cancel(self):
        """Stop the chain: terminate the running subprocess. The
        run loop sees the flag and emits cancelled()."""
        self._cancel_requested = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _run_step(self, argv):
        """Run one chain step, emitting its stdout lines as
        progress. Returns (exit code, stderr text); -1 when the
        step was cancelled. The -u flag matters: without it the
        child block-buffers its stdout into the pipe and no
        progress line arrives until the step exits."""
        argv = [argv[0], "-u"] + argv[1:]
        env = dict(os.environ)
        env.update(self._chain_env)
        proc = subprocess.Popen(
            argv, cwd=TREE_ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self._proc = proc
        try:
            for line in proc.stdout:
                if self._cancel_requested:
                    break
                text = line.strip()
                if text:
                    self.progress.emit(text)
            if self._cancel_requested:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return -1, ""
            proc.wait()
            err = proc.stderr.read() if proc.stderr else ""
            return proc.returncode, err
        finally:
            self._proc = None
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass

    def run(self):
        try:
            fetch_code, fetch_err = self._run_step(
                [sys.executable, "-m", "board.fetch",
                 "--org", self._org])
            if self._cancel_requested:
                self.cancelled.emit()
                return
            if (fetch_code == 2
                    or "No module named" in fetch_err
                    or "ModuleNotFoundError" in fetch_err):
                # Fetch could not run at all: flag has nothing
                # new to read, so the board stays as it is.
                self.finished.emit(2, -1)
                return
            flag_code, _flag_err = self._run_step(
                [sys.executable, "-m", "board.flag"])
            if self._cancel_requested:
                self.cancelled.emit()
                return
            self.finished.emit(fetch_code, flag_code)
        except Exception:
            # Never let the thread die silently: the window shows
            # the plain could-not-run message.
            if self._cancel_requested:
                self.cancelled.emit()
            else:
                self.finished.emit(2, -1)


HOW_TO_USE_TEXT = """How to use Repo Health Board

The board shows every repo in an org, one row each: the last real
commit date, how many files it has, its latest release, whether
it has a CI file, and any health flags. Click a repo name to open
it on GitHub. Click a column heading to sort by it.

What each flag means:

placeholder: the repo has only scaffolding (a README, a LICENSE,
a .gitignore, a SECURITY.md, or files under .github) or is empty.
No real code yet.

no README, no LICENSE, no .gitignore, no SECURITY.md: that file
is missing from the repo.

no description: the repo has no description on GitHub.

no topics: the repo has no topics set on GitHub.

stale (no commit in 90 days): the last real commit is older than
90 days. The date shown is the real commit date, not the date
GitHub lists on the org page.

Suite status only says whether a CI workflow file exists under
.github/workflows: has CI, no CI file, or unknown when the file
list could not be fetched. It never says whether CI passes.

The 60 an hour limit: GitHub allows 60 unauthenticated checks an
hour. Each repo takes a few checks, so a big org can hit the
limit partway through a refresh. When that happens the board
keeps the last good data and tells you when to try again.

The chain: the board is three small pieces, and each one runs on
its own from the terminal:

python -m board.fetch --org BROKE-N-BORED
    Checks the org on GitHub and writes repos.json.

python -m board.flag
    Reads repos.json and writes the flagged board
    (flagged.json and board.txt).

This viewer shows the flagged board. Its Refresh button runs
both pieces for you.

The checks are mechanical only: missing files, old commits,
empty repos. The board never judges whether a repo is good.

Debug report: File, Generate debug report writes a file you can
send to broke.n.bored.studio@gmail.com if something breaks.
"""


class HowToUseWindow(QWidget):
    """The built-in How to Use index. Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use Repo Health Board")
        self.resize(560, 560)
        layout = QVBoxLayout(self)
        text = QTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(HOW_TO_USE_TEXT)
        layout.addWidget(text)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)


class MainWindow(QMainWindow):
    def __init__(self, settings=None, logger=None, qsettings=None,
                 chain_env=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.settings = settings or Settings()
        self.logger = logger or make_logger()
        self.logger.install_crash_handler()
        self._qsettings = qsettings
        self._chain_env = dict(chain_env or {})
        self._board = None        # the loaded flagged.json dict
        self._rows = []           # row dicts, in file order
        self._displayed_rows = []  # row dicts, in table order
        self._sort_column = COL_REPO
        self._sort_order = Qt.AscendingOrder
        self._worker = None
        self._how_to_use = None
        self._rate_notice = None
        self._shown_once = False
        self._user_selecting = False
        self._build_ui()
        self._restore_geometry()
        self._load_board()

    # -- construction -------------------------------------------------
    def _build_ui(self):
        self._build_menus()
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        org_label = QLabel("Org:", central)
        top_row.addWidget(org_label)
        self.org_field = QLineEdit(central)
        self.org_field.setObjectName("orgField")
        self.org_field.setText(self.settings.org)
        self.org_field.returnPressed.connect(self._on_refresh)
        top_row.addWidget(self.org_field, 1)
        self.refresh_button = QPushButton("Refresh", central)
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.clicked.connect(self._on_refresh)
        top_row.addWidget(self.refresh_button)
        self.cancel_button = QPushButton("Cancel", central)
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        top_row.addWidget(self.cancel_button)
        root.addLayout(top_row)

        self.empty_label = QLabel(EMPTY_BOARD_MESSAGE, central)
        self.empty_label.setObjectName("emptyStateLabel")
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        self.table = QTableWidget(0, len(COLUMNS), central)
        self.table.setObjectName("boardTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(
            QTableWidget.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)
        header.setSectionResizeMode(
            COL_FLAGS, QHeaderView.ResizeMode.Stretch)
        for column in (COL_COMMIT, COL_FILES, COL_RELEASE,
                       COL_SUITE):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(COL_REPO, 200)
        # U6: select nothing by default. Qt can auto-select the
        # first row when the table gains focus, so the window
        # watches for that and clears it, keeping only selections
        # the user makes with the mouse or keyboard (see
        # eventFilter and _on_current_cell_changed).
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        self.table.currentCellChanged.connect(
            self._on_current_cell_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self.table, 1)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _build_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        export_action = QAction("Export board", self)
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)
        report_action = QAction("Generate debug report", self)
        report_action.triggered.connect(self._on_debug_report)
        file_menu.addAction(report_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menu_bar.addMenu("Help")
        how_action = QAction("How to Use", self)
        how_action.triggered.connect(self._on_how_to_use)
        help_menu.addAction(how_action)

    # -- geometry -----------------------------------------------------
    def _settings_store(self):
        if self._qsettings is not None:
            return self._qsettings
        from PySide6.QtCore import QSettings
        return QSettings("BrokeNBored", APP_DISPLAY_NAME)

    def _restore_geometry(self):
        try:
            saved = self._settings_store().value("geometry")
        except Exception:
            saved = None
        if saved:
            try:
                self.restoreGeometry(QByteArray(saved))
                return
            except Exception:
                pass
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        try:
            self._settings_store().setValue(
                "geometry", self.saveGeometry())
        except Exception:
            pass
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            # Nothing selected by default, and no button
            # pre-focused: focus lands on the table, which
            # selects nothing (any auto-select Qt does on
            # focus-in is cleared by _on_current_cell_changed).
            self.table.setFocus()

    def eventFilter(self, obj, event):
        # A mouse press or key press on the table means the user
        # is choosing a row; focus arriving on its own does not.
        # The filter runs before the table's own handler, so the
        # flag is set before the selection changes.
        if event.type() == QEvent.FocusIn:
            self._user_selecting = False
        elif event.type() in (QEvent.MouseButtonPress,
                              QEvent.KeyPress):
            self._user_selecting = True
        return super().eventFilter(obj, event)

    def _on_current_cell_changed(self, row, _column, _prev_row,
                                 _prev_column):
        if row != -1 and not self._user_selecting:
            # Qt auto-selected the first row on focus-in. U6 says
            # select nothing by default, so clear it. Clearing
            # fires this slot again with -1, which does nothing.
            self.table.setCurrentCell(-1, -1)
            self.table.clearSelection()
        self._user_selecting = False

    # -- board loading ------------------------------------------------
    def _load_board(self):
        """Load flagged.json and show it. A missing or broken file
        is an empty table with a plain message, never a crash."""
        self._board = load_flagged_board()
        self._rows = []
        if self._board is not None:
            org = self._board.get("org")
            if isinstance(org, str) and org:
                self.org_field.setText(org)
            for entry in self._board.get("rows") or []:
                if not isinstance(entry, dict):
                    continue
                self._rows.append(self._row_from_entry(entry))
        self._sort_rows()
        self._fill_table()
        self._update_status_from_board()

    @staticmethod
    def _row_from_entry(entry):
        health = entry.get("health") or {}
        flags = entry.get("flags") or []
        labels = [flag.get("label") or flag.get("kind") or ""
                  for flag in flags if isinstance(flag, dict)]
        commit_date = parse_iso_date(
            health.get("last_commit_date"))
        return {
            "name": health.get("name") or "",
            "url": health.get("html_url") or "",
            "description": health.get("description") or "",
            "commit_text": (commit_date.strftime("%Y-%m-%d")
                            if commit_date else "unknown"),
            "commit_ts": (commit_date.timestamp()
                          if commit_date else None),
            "files": health.get("file_count"),
            "release": health.get("latest_release_tag"),
            "suite": entry.get("suite") or "unknown",
            "labels": labels,
            "flag_count": len(labels),
        }

    def _update_status_from_board(self):
        if self._board is None:
            self.status_bar.showMessage(EMPTY_BOARD_MESSAGE)
            return
        org = self._board.get("org") or self.settings.org
        fetched = format_fetched_at(self._board.get("fetched_at"))
        counts = self._board.get("counts") or {}
        total = counts.get("total", len(self._rows))
        flagged = counts.get("flagged", 0)
        self.status_bar.showMessage(
            "Org %s, board fetched %s, %d repos, %d flagged"
            % (org, fetched, total, flagged))

    # -- table --------------------------------------------------------
    def _sort_key(self, row):
        if self._sort_column == COL_REPO:
            return row["name"].lower()
        if self._sort_column == COL_COMMIT:
            return row["commit_ts"]
        if self._sort_column == COL_FILES:
            return row["files"]
        if self._sort_column == COL_RELEASE:
            return row["release"]
        if self._sort_column == COL_SUITE:
            return row["suite"]
        return row["flag_count"]

    def _sort_rows(self):
        """Sort the rows by the current column. Rows with an
        unknown value for the column sort last, in both
        directions: an unknown date is never first."""
        descending = self._sort_order == Qt.DescendingOrder
        known = []
        unknown = []
        for row in self._rows:
            if self._sort_key(row) is None:
                unknown.append(row)
            else:
                known.append(row)
        known.sort(key=self._sort_key, reverse=descending)
        self._displayed_rows = known + unknown

    def _on_header_clicked(self, column):
        if column == self._sort_column:
            self._sort_order = (
                Qt.DescendingOrder
                if self._sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder)
        else:
            self._sort_column = column
            self._sort_order = Qt.AscendingOrder
        self._sort_rows()
        self._fill_table()
        self.table.horizontalHeader().setSortIndicator(
            self._sort_column, self._sort_order)

    def _fill_table(self):
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._displayed_rows))
            for index, row in enumerate(self._displayed_rows):
                name_item = QTableWidgetItem(row["name"])
                name_item.setForeground(QColor("#e8a33d"))
                font = QFont()
                font.setUnderline(True)
                name_item.setFont(font)
                name_item.setToolTip(
                    row["url"] or "No GitHub link for this repo")
                self.table.setItem(index, COL_REPO, name_item)
                self.table.setItem(
                    index, COL_COMMIT,
                    QTableWidgetItem(row["commit_text"]))
                files = ("unknown" if row["files"] is None
                         else str(row["files"]))
                self.table.setItem(
                    index, COL_FILES,
                    QTableWidgetItem(files))
                self.table.setItem(
                    index, COL_RELEASE,
                    QTableWidgetItem(row["release"] or "none"))
                self.table.setItem(
                    index, COL_SUITE,
                    QTableWidgetItem(row["suite"]))
                if row["labels"]:
                    flag_text = "%d: %s" % (
                        row["flag_count"], ", ".join(row["labels"]))
                else:
                    flag_text = "ok"
                flag_item = QTableWidgetItem(flag_text)
                flag_item.setToolTip(flag_text)
                self.table.setItem(index, COL_FLAGS, flag_item)
        finally:
            self.table.blockSignals(False)
        self.table.setCurrentCell(-1, -1)
        self.table.clearSelection()
        self.empty_label.setVisible(not self._displayed_rows)
        if self._displayed_rows:
            self.table.horizontalHeader().setSortIndicator(
                self._sort_column, self._sort_order)

    def _on_cell_clicked(self, row, column):
        if column != COL_REPO:
            return
        if 0 <= row < len(self._displayed_rows):
            url = self._displayed_rows[row]["url"]
            if url:
                self.logger.action("opened %s on GitHub"
                                   % self._displayed_rows[row]
                                   ["name"])
                QDesktopServices.openUrl(QUrl(url))

    # -- refresh (the chain, in a worker thread) ----------------------
    def _on_refresh(self):
        if self._worker is not None:
            return
        org = self.org_field.text().strip() or DEFAULT_ORG
        self.org_field.setText(org)
        self.settings.org = org
        try:
            self.settings.save()
        except OSError as exc:
            self.logger.warning("could not save settings: %s", exc)
        self.logger.action("refresh started for org %s" % org)
        self._worker = RefreshWorker(org,
                                     chain_env=self._chain_env,
                                     parent=self)
        self._worker.progress.connect(self._on_refresh_progress)
        self._worker.finished.connect(self._on_refresh_finished)
        self._worker.cancelled.connect(self._on_refresh_cancelled)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self.refresh_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_bar.showMessage("Checking %s..." % org)
        self._worker.start()

    def _on_refresh_progress(self, line):
        self.status_bar.showMessage(line)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_bar.showMessage("Cancelling...")

    def _on_refresh_cancelled(self):
        self._worker = None
        self.refresh_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_bar.showMessage(
            "Refresh cancelled. The board on screen is unchanged.")
        self.logger.action("refresh cancelled")

    def _show_rate_notice(self, message):
        """The rate-limit notice: non-modal, so it never traps the
        window behind a dialog."""
        if self._rate_notice is None:
            self._rate_notice = QMessageBox(self)
            self._rate_notice.setWindowTitle(
                "GitHub limit reached")
            self._rate_notice.setIcon(QMessageBox.Information)
            self._rate_notice.setModal(False)
        self._rate_notice.setText(message)
        self._rate_notice.show()
        self._rate_notice.raise_()

    def _on_refresh_finished(self, fetch_code, flag_code):
        self._worker = None
        self.refresh_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._load_board()
        board = self._board or {}
        if fetch_code == 2:
            self.status_bar.showMessage(
                "Could not check GitHub. The board on screen is "
                "unchanged.")
            self.logger.warning("refresh could not run "
                                "(fetch exit 2)")
            return
        if flag_code != 0:
            self.status_bar.showMessage(
                "The check ran but the board could not be flagged. "
                "The board on screen is unchanged.")
            self.logger.warning("refresh flag step failed "
                                "(flag exit %s)" % flag_code)
            return
        # Fetch exit 1 is partial: rate-limited OR per-repo
        # errors. Only the flagged board knows which.
        if board.get("rate_limited"):
            when = plain_reset_time(board.get("rate_reset_at"))
            message = ("GitHub allows 60 unauthenticated checks an "
                       "hour, and the limit was reached. The board "
                       "on screen is the last good one. Try again "
                       "%s." % when)
            self.status_bar.showMessage(message)
            self._show_rate_notice(message)
            self.logger.warning("refresh rate limited; "
                                "try again %s" % when)
            return
        if fetch_code == 1:
            self.status_bar.showMessage(
                "Some repos could not be checked. The board shows "
                "what was fetched.")
            self.logger.warning("refresh partial (fetch exit 1)")
            return
        fetched = board.get("fetched_at")
        if fetched:
            self.settings.last_refresh = fetched
            try:
                self.settings.save()
            except OSError:
                pass
        counts = board.get("counts") or {}
        total = counts.get("total", len(self._rows))
        flagged = counts.get("flagged", 0)
        self.status_bar.showMessage(
            "Board updated: %d repos, %d flagged."
            % (total, flagged))
        self.logger.action("refresh finished: %d repos, "
                           "%d flagged" % (total, flagged))

    # -- menus --------------------------------------------------------
    def _board_text(self):
        """The displayed rows as text (the board.txt shape), used
        when board.txt itself is missing."""
        org = (self._board.get("org") if self._board
               else self.org_field.text().strip() or DEFAULT_ORG)
        fetched = (self._board.get("fetched_at") if self._board
                   else None)
        lines = ["Repo Health Board: %s (fetched %s)"
                 % (org, fetched or "unknown")]
        flagged = 0
        for row in self._displayed_rows:
            if row["labels"]:
                flag_text = ", ".join(row["labels"])
                flagged += 1
            else:
                flag_text = "ok"
            files = ("unknown" if row["files"] is None
                     else "%d files" % row["files"])
            lines.append("%s | %s | %s | %s | %s"
                         % (row["name"], row["commit_text"],
                            files, row["release"] or "none",
                            flag_text))
        total = len(self._displayed_rows)
        lines.append("%d repos, %d flagged, %d ok"
                     % (total, flagged, total - flagged))
        return "\n".join(lines) + "\n"

    def export_board_to(self, path):
        """Write the board text to path: board.txt when it exists,
        else the displayed rows as text. Returns the path."""
        text_path = default_board_text_path()
        if os.path.isfile(text_path):
            with open(text_path, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = self._board_text()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _on_export(self):
        default = os.path.join(os.path.expanduser("~"),
                               "repo-health-board.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export board", default, "Text files (*.txt)")
        if not path:
            return
        try:
            self.export_board_to(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed",
                                "Could not write the board to:\n"
                                "%s\n\n%s" % (path, exc))
            return
        self.status_bar.showMessage("Board exported to %s" % path)
        self.logger.action("board exported to %s" % path)

    def _on_debug_report(self):
        path = self.logger.generate_report()
        self.status_bar.showMessage("Debug report written to %s"
                                    % path)
        QMessageBox.information(
            self, "Debug report",
            "Debug report written to:\n%s\n\nSend it to %s if "
            "something is broken." % (path, REPORT_EMAIL))

    def _on_how_to_use(self):
        if self._how_to_use is None:
            self._how_to_use = HowToUseWindow(self)
        self._how_to_use.show()
        self._how_to_use.raise_()
        self._how_to_use.activateWindow()


def run_gui():
    """Open the window. Returns the app exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("BrokeNBored")
    app.setStyleSheet(DARK_STYLESHEET)
    lock = try_single_instance()
    if lock is None:
        print("Repo Health Board is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
