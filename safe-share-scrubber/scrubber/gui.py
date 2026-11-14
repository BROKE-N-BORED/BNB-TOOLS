"""Qt GUI for Safe Share Scrubber. A THIN viewer: it does no
scrubbing and no verifying itself. It runs `python -m scrubber
scrub --json` and `python -m scrubber verify --json` as
subprocesses in a worker thread, parses the JSON the CLI prints,
and displays the results. The report pane shows the report text
by reading the report file the CLI wrote, so the CLI is the one
source of truth for displayed text.

Import rule (enforced by a test that parses this file with ast):
this module must NOT import scrubber.core, scrubber.report,
scrubber.cli, or scrubber.verify. It imports Qt, scrubber.settings,
scrubber.logsetup (for make_logger), and the standard library
only. The GUI logs no user-supplied text, only counts and exit
codes, so it needs no safe_log_text.

One main window: a file list on the left, the report on the right.
Drop files in, press Scrub, get a safe copy of each file plus a
short report; press Verify to scan without writing anything.
Runs happen in a worker thread; the window never blocks. Single
instance via QLockFile. Geometry is remembered between runs.

Visible text rules (design rules U11, U33): no em-dashes anywhere,
no bare & in any label. Keep it that way when editing strings.
"""

import json
import os
import subprocess
import sys

from PySide6.QtCore import (QByteArray, QEvent, QLockFile, Qt, QThread,
                            Signal)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton,
                               QSplitter, QStatusBar, QTextEdit,
                               QVBoxLayout, QWidget)

from .logsetup import make_logger
from .settings import Settings, cache_dir

APP_DISPLAY_NAME = "Safe Share Scrubber"
DEFAULT_WIDTH = 1000
DEFAULT_HEIGHT = 620

# The honest caveat, in plain words. It also appears as a label in
# the window and in the How to Use window. Kept word for word with
# report.py's copy; the GUI cannot import report, so the text lives
# here too. If the wording ever changes, change both copies.
CAVEAT_TEXT = (
    "This scrubber works from patterns. It can only catch secrets "
    "it has a pattern for, so it cannot prove a file holds no "
    "secret it does not know about. Read the safe copy before you "
    "share it."
)

# The honest caveat for verify, in plain words: the same warning
# as CAVEAT_TEXT, minus the safe-copy sentence, because verify
# writes no safe copy. Kept word for word with cli.VERIFY_CAVEAT;
# the GUI cannot import cli, so the text lives here too.
VERIFY_CAVEAT = (
    "This scanner works from patterns. It can only catch secrets "
    "it has a pattern for, so it cannot prove a file holds no "
    "secret it does not know about."
)

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #23262b; color: #e8e8e8;
    font-size: 13px; }
QPushButton { background-color: #33373d; border: 1px solid #4a4f56;
    border-radius: 5px; padding: 4px 12px; color: #e8e8e8; }
QPushButton:hover { background-color: #3d4249; }
QPushButton:pressed { background-color: #2b2e33; }
QPushButton:disabled { color: #777777; }
QPushButton:focus, QListWidget:focus, QTextEdit:focus {
    border: 2px solid #e8a33d; outline: none; }
QPushButton#scrubButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#scrubButton:hover { background-color: #a06f22; }
QPushButton#scrubButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QTextEdit, QListWidget { background-color: #1a1d21;
    border: 1px solid #3a3e44; border-radius: 4px; padding: 3px;
    color: #e8e8e8; }
QListWidget::item:selected { background-color: #3d4249; }
QLabel#caveatLabel { color: #b0b0b0; font-style: italic; }
QLabel#busyLight { border-radius: 6px; min-width: 12px; max-width: 12px;
    min-height: 12px; max-height: 12px; background-color: #555555; }
QLabel#busyLight[busy="true"] { background-color: #e8a33d; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
"""


def package_root():
    """The folder holding the scrubber package: the subprocess runs
    there so `python -m scrubber` finds the package."""
    return os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))


def lock_file_path():
    return os.path.join(cache_dir(), "single-instance.lock")


def try_single_instance():
    """Hold the single-instance lock. Returns the QLockFile, or None
    when another copy already holds it."""
    os.makedirs(cache_dir(), exist_ok=True)
    lock = QLockFile(lock_file_path())
    lock.setStaleLockTime(0)
    # This PySide6 build requires the timeout argument.
    if lock.tryLock(0):
        return lock
    return None


class CliWorker(QThread):
    """Run one CLI command (`scrub --json` or `verify --json`) in a
    worker thread. Never blocks the UI.

    done carries the parsed JSON result list plus the CLI exit
    code. A nonzero exit is not a failure on its own: verify exits
    1 when it finds a secret, and scrub exits 1 when one file in
    a batch fails, and both still print good JSON. failed carries
    a display message plus the exit code (-1 when the process never
    started). Cancel kills the subprocess outright (SIGKILL), it
    does not just abandon it.
    """

    done = Signal(list, int)
    failed = Signal(str, int)
    cancelled = Signal()

    def __init__(self, command, paths, parent=None):
        super().__init__(parent)
        self._command = command
        self._paths = list(paths)
        self._cancelled = False
        self._proc = None

    def cancel(self):
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # SIGKILL: the run stops now, not when the CLI gets
            # around to noticing.
            proc.kill()

    def run(self):
        root = package_root()
        env = dict(os.environ)
        path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = root if not path else root + os.pathsep + path
        argv = [sys.executable, "-m", "scrubber", self._command,
                "--json"] + self._paths
        try:
            self._proc = subprocess.Popen(
                argv, cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            self.failed.emit("Could not start the command: %s"
                             % exc, -1)
            return
        try:
            stdout, stderr = self._proc.communicate()
        except Exception as exc:  # never let the thread die silently
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit("The command failed: %s" % exc,
                                 -1)
            return
        if self._cancelled:
            self.cancelled.emit()
            return
        exit_code = self._proc.returncode
        try:
            results = json.loads(stdout)
        except ValueError:
            detail = stderr.strip().splitlines()
            detail = detail[-1] if detail else "no output"
            self.failed.emit(
                "The %s command failed (exit %d): %s"
                % (self._command, exit_code, detail[:200]),
                exit_code)
            return
        if not isinstance(results, list):
            self.failed.emit(
                "The %s command printed unexpected output "
                "(exit %d)" % (self._command, exit_code),
                exit_code)
            return
        self.done.emit(results, exit_code)


def _group_findings(findings):
    """Findings grouped by kind, each with its sorted line list."""
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding["kind"], []).append(
            finding["line"])
    return {kind: sorted(lines) for kind, lines in grouped.items()}


def _lines_text(lines):
    if len(lines) == 1:
        return "line %d" % lines[0]
    return "lines %s" % ", ".join(str(n) for n in lines)


def build_verify_display(results):
    """The verify display text, built from the parsed JSON. Verify
    writes no report file, so the window formats the findings
    itself: file, secrets by kind with line numbers, and a plain
    verdict line. Findings carry kind and line only, never a
    secret value."""
    parts = []
    for result in results:
        out = []
        out.append("File: %s" % result["path"])
        if result.get("error"):
            out.append("Could not scan this file: %s"
                       % result["error"])
            out.append("Verdict: Not scanned")
        elif result.get("skipped_reason"):
            out.append("Skipped: %s." % result["skipped_reason"])
            out.append("Verdict: Not scanned")
        else:
            findings = result.get("findings") or []
            out.append("Secrets found: %d" % len(findings))
            for kind, lines in sorted(
                    _group_findings(findings).items()):
                out.append("  %s: %s" % (kind, _lines_text(lines)))
            if not findings:
                out.append("  None.")
            if findings:
                out.append("Verdict: Not safe to share: "
                           "secrets found")
            else:
                out.append("Verdict: Safe to share")
        parts.append("\n".join(out) + "\n")
    parts.append(VERIFY_CAVEAT + "\n")
    return "\n".join(parts)


HOW_TO_USE_TEXT = """How to use Safe Share Scrubber

1. Add files: drag text or log files onto the window, or use File,
   Add files. Any file works. Binary files are skipped and the
   report says so.

2. Press Verify to check the files without changing anything. It
   lists the secrets found, by kind and line number, and writes
   no files at all.

3. Press Scrub to redact what was found. Each file gets a safe
   copy next to it, with ".safe" in the name, and a short report
   file. Your original file is never changed.

4. Read the report on the right. It lists the secrets found, by
   kind and line number. It never shows the secret itself.

5. Share the safe copy, not the original. The safe copy has every
   secret the scrubber found replaced with a marker like
   [REDACTED AWS KEY].

6. Debug report: File, Generate debug report writes a file you
   can send to broke.n.bored.studio@gmail.com if something breaks.

%s
""" % CAVEAT_TEXT


class HowToUseWindow(QWidget):
    """The built-in How to Use index (U22). Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use Safe Share Scrubber")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        text = QTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(HOW_TO_USE_TEXT)
        layout.addWidget(text)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)


class MainWindow(QMainWindow):
    def __init__(self, settings=None, logger=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.settings = settings or Settings()
        self.logger = logger or make_logger()
        self.logger.install_crash_handler()
        self.files = []           # absolute paths, in list order
        self._results = {}        # path -> last result dict
        self._worker = None
        self._run_mode = None     # "scrub" or "verify", while running
        self._how_to_use = None
        self._shown_once = False
        self._user_selecting = False
        self._build_ui()
        self._restore_geometry()
        self._update_buttons()

    # -- construction -------------------------------------------------
    def _build_ui(self):
        self._build_menus()
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Horizontal, central)
        root.addWidget(splitter)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.empty_label = QLabel(
            "No files yet. Add files or drop them here.", left)
        self.empty_label.setObjectName("emptyStateLabel")
        left_layout.addWidget(self.empty_label)
        self.file_list = QListWidget(left)
        self.file_list.setObjectName("fileList")
        # U6: select nothing by default. Qt auto-selects the first
        # row when the list gains focus, so the window watches for
        # that and clears it, keeping only selections the user
        # makes with the mouse or keyboard (see eventFilter and
        # _on_row_changed).
        self.file_list.installEventFilter(self)
        self.file_list.viewport().installEventFilter(self)
        self.file_list.currentRowChanged.connect(
            self._on_row_changed)
        left_layout.addWidget(self.file_list, 1)
        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add files", left)
        self.add_button.setObjectName("addButton")
        self.add_button.clicked.connect(self._on_add_files)
        button_row.addWidget(self.add_button)
        self.scrub_button = QPushButton("Scrub", left)
        self.scrub_button.setObjectName("scrubButton")
        self.scrub_button.clicked.connect(self._on_scrub)
        button_row.addWidget(self.scrub_button)
        self.verify_button = QPushButton("Verify", left)
        self.verify_button.setObjectName("verifyButton")
        self.verify_button.clicked.connect(self._on_verify)
        button_row.addWidget(self.verify_button)
        self.cancel_button = QPushButton("Cancel", left)
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_button)
        left_layout.addLayout(button_row)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.report_text = QTextEdit(right)
        self.report_text.setObjectName("reportText")
        self.report_text.setReadOnly(True)
        self.report_text.setPlaceholderText(
            "The report appears here after you press Scrub "
            "or Verify.")
        right_layout.addWidget(self.report_text, 1)
        self.caveat_label = QLabel(CAVEAT_TEXT, right)
        self.caveat_label.setObjectName("caveatLabel")
        self.caveat_label.setWordWrap(True)
        right_layout.addWidget(self.caveat_label)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 560])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.busy_light = QLabel(self.status_bar)
        self.busy_light.setObjectName("busyLight")
        self.busy_light.setProperty("busy", False)
        self.status_bar.addPermanentWidget(self.busy_light)
        self.status_bar.showMessage("Ready")

        self.setAcceptDrops(True)

    def _build_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        add_action = QAction("Add files", self)
        add_action.setShortcut(QKeySequence.Open)
        add_action.triggered.connect(self._on_add_files)
        file_menu.addAction(add_action)
        scrub_action = QAction("Scrub", self)
        scrub_action.triggered.connect(self._on_scrub)
        file_menu.addAction(scrub_action)
        verify_action = QAction("Verify", self)
        verify_action.triggered.connect(self._on_verify)
        file_menu.addAction(verify_action)
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
    def _restore_geometry(self):
        saved = self.settings.get_geometry()
        if saved:
            self.restoreGeometry(QByteArray(saved))
        else:
            self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        self.settings.set_geometry(bytes(self.saveGeometry()))
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            # Nothing selected by default, and no button pre-focused:
            # focus lands on the file list, which selects nothing
            # (the auto-select Qt does on focus-in is cleared by
            # _on_row_changed).
            self.file_list.setFocus()

    def eventFilter(self, obj, event):
        # A mouse press or key press on the file list means the
        # user is choosing a row; focus arriving on its own does
        # not. The filter runs before the list's own handler, so
        # the flag is set before the selection changes.
        if event.type() == QEvent.FocusIn:
            self._user_selecting = False
        elif event.type() in (QEvent.MouseButtonPress,
                              QEvent.KeyPress):
            self._user_selecting = True
        return super().eventFilter(obj, event)

    def _on_row_changed(self, row):
        if row != -1 and not self._user_selecting:
            # Qt auto-selected the first row on focus-in. U6 says
            # select nothing by default, so clear it. Clearing
            # fires this slot again with -1, which does nothing.
            self.file_list.setCurrentRow(-1)
        self._user_selecting = False

    # -- file list ----------------------------------------------------
    def add_files(self, paths):
        """Add files to the list. Returns (added, failures)."""
        added = 0
        failures = []
        for path in paths:
            if not os.path.isfile(path):
                failures.append((path, "not a file"))
                continue
            full = os.path.abspath(path)
            if full in self.files:
                continue
            self.files.append(full)
            self.file_list.addItem(QListWidgetItem(""))
            added += 1
        self._refresh_list()
        self._update_buttons()
        self.empty_label.setVisible(not self.files)
        # Counts only: the GUI logs no user-supplied text.
        if added:
            self.logger.action("added %d file(s)" % added)
        if failures:
            self.logger.warning("could not read %d file(s)"
                                % len(failures))
            lines = ["Could not read these files:"]
            for path, reason in failures:
                lines.append("%s: %s"
                             % (os.path.basename(path), reason))
            QMessageBox.information(self, "Some files could not "
                                    "be read", "\n".join(lines))
        return added, failures

    def _refresh_list(self):
        for row, path in enumerate(self.files):
            item = self.file_list.item(row)
            name = os.path.basename(path)
            result = self._results.get(path)
            if result is None:
                item.setText(name)
            elif result.get("error"):
                item.setText("%s: could not read" % name)
            elif result.get("skipped") or result.get("skipped_reason"):
                item.setText("%s: skipped, binary file" % name)
            elif result["secrets_found"]:
                if result.get("mode") == "verify":
                    item.setText("%s: %d secret(s) found"
                                 % (name, result["secrets_found"]))
                else:
                    item.setText("%s: %d secret(s) redacted"
                                 % (name, result["secrets_found"]))
            else:
                item.setText("%s: no secrets found" % name)

    def _update_buttons(self):
        running = self._worker is not None
        self.scrub_button.setEnabled(bool(self.files)
                                     and not running)
        self.verify_button.setEnabled(bool(self.files)
                                      and not running)
        self.add_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _set_busy(self, busy, message=None):
        self.busy_light.setProperty("busy", busy)
        self.busy_light.style().unpolish(self.busy_light)
        self.busy_light.style().polish(self.busy_light)
        if message is not None:
            self.status_bar.showMessage(message)
        self._update_buttons()

    # -- scrub and verify ---------------------------------------------
    def _start_run(self, mode):
        if not self.files or self._worker is not None:
            return
        self._run_mode = mode
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("%s started for %d file(s)"
                           % (mode, len(self.files)))
        self._worker = CliWorker(mode, list(self.files), self)
        self._worker.done.connect(self._on_run_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.cancelled.connect(self._on_run_cancelled)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self._set_busy(True, "%s..." % mode.capitalize())
        self._worker.start()

    def _on_scrub(self):
        self._start_run("scrub")

    def _on_verify(self):
        self._start_run("verify")

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    def _read_scrub_reports(self, results):
        """The report pane text for a scrub run: the report files
        the CLI wrote, read back. The CLI is the one source of
        truth for displayed text; a result with no report file
        (unreadable, or the report write failed) gets one plain
        line from the JSON instead."""
        texts = []
        for result in results:
            report_path = result.get("report_path")
            text = None
            if report_path:
                try:
                    with open(report_path, encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    text = None
            if text is None:
                if result.get("error"):
                    text = ("File: %s\nCould not read or write "
                            "this file: %s\nNo safe copy was "
                            "written.\nVerdict: %s\n"
                            % (result["path"], result["error"],
                               result.get("verdict") or ""))
                else:
                    text = ("File: %s\nNo report file was "
                            "written.\nVerdict: %s\n"
                            % (result["path"],
                               result.get("verdict") or ""))
            texts.append(text)
        return "\n".join(texts)

    def _on_run_done(self, results, exit_code):
        mode = self._run_mode
        self._worker = None
        self._run_mode = None
        self._set_busy(False)
        total = 0
        skipped = 0
        for result in results:
            result["mode"] = mode
            self._results[result["path"]] = result
            total += result["secrets_found"]
            if result.get("skipped") or result.get("skipped_reason"):
                skipped += 1
        # Counts and the exit code only: no user-supplied text.
        self.logger.action(
            "%s finished: exit %d, %d file(s), %d finding(s)"
            % (mode, exit_code, len(results), total))
        self._refresh_list()
        if mode == "scrub":
            self.report_text.setPlainText(
                self._read_scrub_reports(results))
            if skipped:
                self.status_bar.showMessage(
                    "Scrubbed %d file(s): %d secret(s) redacted, "
                    "%d skipped (binary)" % (len(results), total,
                                             skipped))
            else:
                self.status_bar.showMessage(
                    "Scrubbed %d file(s): %d secret(s) redacted"
                    % (len(results), total))
        else:
            self.report_text.setPlainText(
                build_verify_display(results))
            if skipped:
                self.status_bar.showMessage(
                    "Verified %d file(s): %d secret(s) found, "
                    "%d not scanned" % (len(results), total,
                                        skipped))
            else:
                self.status_bar.showMessage(
                    "Verified %d file(s): %d secret(s) found"
                    % (len(results), total))

    def _on_run_failed(self, message, exit_code):
        mode = self._run_mode
        self._worker = None
        self._run_mode = None
        self._set_busy(False, "Ready")
        self.report_text.setPlainText(message)
        # The exit code only: the message may carry CLI stderr,
        # which can hold user-supplied text.
        self.logger.warning("%s failed: exit %d"
                            % (mode or "run", exit_code))

    def _on_run_cancelled(self):
        mode = self._run_mode
        self._worker = None
        self._run_mode = None
        self._set_busy(False, "%s cancelled"
                        % (mode or "Run").capitalize())
        self.logger.action("%s cancelled" % (mode or "run"))

    # -- menus --------------------------------------------------------
    def _on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", "", "All files (*)")
        if paths:
            self.add_files(paths)

    def _on_debug_report(self):
        path = self.logger.generate_report()
        self.status_bar.showMessage("Debug report written to %s"
                                    % path)
        QMessageBox.information(
            self, "Debug report",
            "Debug report written to:\n%s\n\nSend it to "
            "broke.n.bored.studio@gmail.com if something is broken."
            % path)

    def _on_how_to_use(self):
        if self._how_to_use is None:
            self._how_to_use = HowToUseWindow(self)
        self._how_to_use.show()
        self._how_to_use.raise_()
        self._how_to_use.activateWindow()

    # -- drag and drop ------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = [u.toLocalFile() for u in event.mimeData().urls()]
            if any(os.path.isfile(u) for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        files = [p for p in paths if os.path.isfile(p)]
        if files:
            self.add_files(files)
        event.acceptProposedAction()


def run_gui():
    """Open the window. Returns the app exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("BrokeNBored")
    app.setStyleSheet(DARK_STYLESHEET)
    lock = try_single_instance()
    if lock is None:
        print("Safe Share Scrubber is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
