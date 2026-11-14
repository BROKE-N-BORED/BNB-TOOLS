"""Qt GUI for Song Key BPM. A THIN viewer: it does no analysis
itself. It runs `songkey analyze --json` and `songkey export` as
subprocesses in a worker thread, parses the JSON the analyze
command prints, and displays the results in a table. The export
step writes a CSV from the results the window already holds, so
the window and the terminal always agree.

Import rule (enforced by a test that parses this file with ast):
this module must NOT import songkey.decode, songkey.tempo,
songkey.key, songkey.analyze, songkey.export, songkey.cli,
aubio, miniaudio, or numpy. It imports Qt, songkey.settings,
songkey.logsetup (for make_logger), and the standard library
only. The GUI logs no user-supplied text, only counts and exit
codes.

One main window: a file list on the left, the results table on
the right. Drop audio files in, press Analyze, read the BPM and
key of each file; press Export to write the table as a CSV.
Runs happen in a worker thread; the window never blocks. Single
instance via QLockFile. Geometry is remembered between runs.

Visible text rules (design rules U11, U33): no em-dashes anywhere,
no bare & in any label. Keep it that way when editing strings.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import (QByteArray, QEvent, QLockFile, QSettings,
                            Qt, QThread, Signal)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton,
                               QSplitter, QStatusBar,
                               QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from .logsetup import make_logger
from .settings import Settings, data_dir

APP_DISPLAY_NAME = "Song Key BPM"
DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 650
ORG_NAME = "BrokeNBored"
QSETTINGS_APP_NAME = "SongKeyBPM"

# Audio files the window accepts, by extension. This is a copy of
# decode.SUPPORTED_EXTENSIONS: the GUI must not import decode, so
# the list lives here too. If decode ever gains an extension,
# add it here as well.
AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".oga")

TABLE_COLUMNS = ("File", "BPM", "Key", "Confidence", "Duration")

# The honest caveat, in plain words. It also appears as a label in
# the window and in the How to Use window. Kept word for word with
# the README's copy; the GUI cannot import anything that holds it,
# so the text lives here too. If the wording ever changes, change
# both copies.
CAVEAT_TEXT = (
    "BPM is a measurement and key is an estimate. Key detection "
    "is approximate: relative major and minor pairs, like C major "
    "and A minor, share the same notes, so a close call between "
    "them is normal. Check by ear."
)

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #23262b; color: #e8e8e8;
    font-size: 13px; }
QPushButton { background-color: #33373d; border: 1px solid #4a4f56;
    border-radius: 5px; padding: 4px 12px; color: #e8e8e8; }
QPushButton:hover { background-color: #3d4249; }
QPushButton:pressed { background-color: #2b2e33; }
QPushButton:disabled { color: #777777; }
QPushButton:focus, QListWidget:focus, QTextEdit:focus,
QTableWidget:focus { border: 2px solid #e8a33d; outline: none; }
QPushButton#analyzeButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#analyzeButton:hover { background-color: #a06f22; }
QPushButton#analyzeButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QTextEdit, QListWidget, QTableWidget { background-color: #1a1d21;
    border: 1px solid #3a3e44; border-radius: 4px; padding: 3px;
    color: #e8e8e8; }
QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #3d4249; }
QHeaderView::section { background-color: #33373d;
    color: #e8e8e8; border: 1px solid #3a3e44; padding: 4px; }
QLabel#caveatLabel { color: #b0b0b0; font-style: italic; }
QLabel#busyLight { border-radius: 6px; min-width: 12px; max-width: 12px;
    min-height: 12px; max-height: 12px; background-color: #555555; }
QLabel#busyLight[busy="true"] { background-color: #e8a33d; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
"""


def package_root():
    """The folder holding the songkey package: the subprocess runs
    there so `python -m songkey` finds the package."""
    return os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))


def lock_file_path():
    return os.path.join(data_dir(), "single-instance.lock")


def try_single_instance():
    """Hold the single-instance lock. Returns the QLockFile, or None
    when another copy already holds it."""
    os.makedirs(data_dir(), exist_ok=True)
    lock = QLockFile(lock_file_path())
    lock.setStaleLockTime(0)
    # This PySide6 build requires the timeout argument.
    if lock.tryLock(0):
        return lock
    return None


def analyze_command():
    """The analyze command prefix: the installed song-key-analyze
    wrapper when it is on PATH, else this Python running
    `python -m songkey analyze` from the tree. The PATH lookup is
    also what lets the tests put a stub analyzer on PATH that
    prints canned JSON, to check the window's parsing without
    waiting on real analysis."""
    wrapper = shutil.which("song-key-analyze")
    if wrapper:
        return [wrapper]
    return [sys.executable, "-m", "songkey", "analyze"]


def export_command():
    """The export command prefix: the installed song-key-export
    wrapper when it is on PATH, else this Python running
    `python -m songkey export` from the tree. Same stub seam as
    analyze_command."""
    wrapper = shutil.which("song-key-export")
    if wrapper:
        return [wrapper]
    return [sys.executable, "-m", "songkey", "export"]


def analyze_argv(paths):
    """Full argv for one analyze run over these paths."""
    return analyze_command() + ["--json"] + list(paths)


def export_argv(results_json_path, out_path):
    """Full argv for one export run: the analyze JSON file in, the
    CSV file out."""
    return export_command() + [results_json_path, "--format",
                               "csv", "--out", out_path]


def collect_audio(paths):
    """Expand files and folders into a sorted list of audio paths.

    Folders are walked recursively; only supported audio files
    are picked up. Returns (files, failures): failures holds
    (path, reason) for paths that were not usable.
    """
    files = []
    failures = []
    for path in paths:
        if os.path.isfile(path):
            if path.lower().endswith(AUDIO_EXTENSIONS):
                files.append(path)
            else:
                failures.append((path, "not an audio file"))
        elif os.path.isdir(path):
            found = []
            for root, dirs, names in os.walk(path):
                dirs.sort()
                for name in sorted(names):
                    if name.lower().endswith(AUDIO_EXTENSIONS):
                        found.append(os.path.join(root, name))
            if not found:
                failures.append((path, "no audio files in it"))
            files.extend(found)
        else:
            failures.append((path, "not a file"))
    return files, failures


def format_bpm(result):
    """The BPM cell: one decimal, marked when confidence is low."""
    bpm = result.get("bpm")
    if bpm is None:
        return "Unknown"
    if result.get("bpm_confidence") == "low":
        return "%.1f (low)" % bpm
    return "%.1f" % bpm


def format_key(result):
    """The Key cell: the key, with the runner-up named on a close
    call, so a relative major/minor call reads like
    "A minor (or C major?)"."""
    if result.get("error"):
        return "Could not read"
    key = result.get("key")
    if key is None:
        return "Unknown"
    if result.get("key_confidence") == "low" and result.get(
            "key_runner_up"):
        return "%s (or %s?)" % (key, result["key_runner_up"])
    return key


def format_confidence(result):
    """The Confidence cell: the key confidence, in plain words."""
    if result.get("error"):
        return "Error"
    confidence = result.get("key_confidence")
    if confidence == "high":
        return "Confident"
    if confidence == "low":
        return "Low"
    return "Unknown"


def format_duration(result):
    """The Duration cell: seconds to one decimal."""
    duration = result.get("duration")
    if duration is None:
        return "Unknown"
    return "%.1f s" % duration


class CliWorker(QThread):
    """Run one CLI command in a worker thread. Never blocks the UI.

    mode "analyze": argv prints a JSON list of result dicts on
    stdout; done carries that list plus the CLI exit code. A
    nonzero exit is not a failure on its own: analyze exits 1
    when no file could be analyzed, and still prints good JSON.

    mode "export": argv writes a CSV file; done carries the CSV
    path plus the CLI exit code. The run only counts as done when
    the exit code is 0 and the CSV file exists.

    failed carries a display message plus the exit code (-1 when
    the process never started). Cancel kills the subprocess
    outright (SIGKILL), it does not just abandon it. cleanup_path,
    when given, is a temp file removed when the run ends however
    it ends.
    """

    done = Signal(object, int)
    failed = Signal(str, int)
    cancelled = Signal()

    def __init__(self, mode, argv, out_path=None, cleanup_path=None,
                 parent=None):
        super().__init__(parent)
        self._mode = mode
        self._argv = list(argv)
        self._out_path = out_path
        self._cleanup_path = cleanup_path
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
        try:
            self._proc = subprocess.Popen(
                self._argv, cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            if self._cancelled:
                # Cancel landed before the process spawned:
                # kill it now, or the run would sit in
                # communicate() until the command finished.
                self._proc.kill()
        except OSError as exc:
            self.failed.emit("Could not start the command: %s"
                             % exc, -1)
            self._cleanup()
            return
        try:
            stdout, stderr = self._proc.communicate()
        except Exception as exc:  # never let the thread die silently
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit("The command failed: %s" % exc,
                                 -1)
            self._cleanup()
            return
        if self._cancelled:
            self.cancelled.emit()
            self._cleanup()
            return
        exit_code = self._proc.returncode
        if self._mode == "export":
            if exit_code == 0 and self._out_path and os.path.isfile(
                    self._out_path):
                self.done.emit(self._out_path, exit_code)
            else:
                detail = stderr.strip().splitlines()
                detail = detail[-1] if detail else "no output"
                self.failed.emit(
                    "The export failed (exit %d): %s"
                    % (exit_code, detail[:200]),
                    exit_code)
            self._cleanup()
            return
        try:
            results = json.loads(stdout)
        except ValueError:
            detail = stderr.strip().splitlines()
            detail = detail[-1] if detail else "no output"
            self.failed.emit(
                "The analyze command failed (exit %d): %s"
                % (exit_code, detail[:200]),
                exit_code)
            self._cleanup()
            return
        if not isinstance(results, list):
            self.failed.emit(
                "The analyze command printed unexpected output "
                "(exit %d)" % exit_code,
                exit_code)
            self._cleanup()
            return
        self.done.emit(results, exit_code)
        self._cleanup()

    def _cleanup(self):
        if self._cleanup_path:
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass


HOW_TO_USE_TEXT = """How to use Song Key BPM

1. Add files: drag audio files (WAV, MP3, FLAC, OGG) onto the
   window, or use File, Add files. You can add several at once,
   or drop a whole folder: every audio file under it is added.

2. Press Analyze. Each file is measured for BPM and key, and the
   table fills in: BPM, key, confidence, and duration. A key
   with low confidence shows its close second choice too, like
   "A minor (or C major?)".

3. Press Export to write the table as a CSV file, next to your
   songs or wherever you pick. Open it in any spreadsheet.

4. BPM needs a beat: a file with no beat, like a chord pad with
   no drums, reports BPM unknown. That is the honest answer, not
   a failure. A file the tool cannot read reports "Could not
   read" in the table.

5. Debug report: File, Generate debug report writes a file you
   can send to broke.n.bored.studio@gmail.com if something breaks.

%s

Check the tool against songs you know: Tomorrow (Silverchair)
is D major at about 147 BPM, Alive (Pearl Jam) is B minor at
75 BPM (150 double-time), Plush (Stone Temple Pilots) is
G minor at 145 BPM.
""" % CAVEAT_TEXT


class HowToUseWindow(QWidget):
    """The built-in How to Use index (U22). Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use Song Key BPM")
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
    def __init__(self, settings=None, logger=None, qsettings=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.settings = settings or Settings()
        self.logger = logger or make_logger()
        self.logger.install_crash_handler()
        # Geometry lives in QSettings, not in the JSON settings
        # store: settings.py holds the last folder and the export
        # format only. Tests pass their own QSettings backend.
        if qsettings is not None:
            self._qsettings = qsettings
        else:
            self._qsettings = QSettings(ORG_NAME, QSETTINGS_APP_NAME)
        self.files = []           # absolute paths, in list order
        self._results = {}        # path -> last result dict
        self._worker = None
        self._run_mode = None     # "analyze" or "export", while running
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
            "No files yet. Add audio files or drop them here.",
            left)
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
        self.analyze_button = QPushButton("Analyze", left)
        self.analyze_button.setObjectName("analyzeButton")
        self.analyze_button.clicked.connect(self._on_analyze)
        button_row.addWidget(self.analyze_button)
        self.export_button = QPushButton("Export", left)
        self.export_button.setObjectName("exportButton")
        self.export_button.clicked.connect(self._on_export)
        button_row.addWidget(self.export_button)
        self.cancel_button = QPushButton("Cancel", left)
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_button)
        left_layout.addLayout(button_row)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.results_table = QTableWidget(right)
        self.results_table.setObjectName("resultsTable")
        self.results_table.setColumnCount(len(TABLE_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(
            list(TABLE_COLUMNS))
        self.results_table.setEditTriggers(
            QTableWidget.NoEditTriggers)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectRows)
        self.results_table.setSelectionMode(
            QTableWidget.SingleSelection)
        self.results_table.horizontalHeader().setStretchLastSection(
            True)
        self.results_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.results_table, 1)
        self.caveat_label = QLabel(CAVEAT_TEXT, right)
        self.caveat_label.setObjectName("caveatLabel")
        self.caveat_label.setWordWrap(True)
        right_layout.addWidget(self.caveat_label)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 680])
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
        analyze_action = QAction("Analyze", self)
        analyze_action.triggered.connect(self._on_analyze)
        file_menu.addAction(analyze_action)
        export_action = QAction("Export results", self)
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
    def _restore_geometry(self):
        saved = self._qsettings.value("window_geometry", None)
        if isinstance(saved, QByteArray):
            self.restoreGeometry(saved)
        else:
            self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        self._qsettings.setValue(
            "window_geometry", QByteArray(self.saveGeometry()))
        self._qsettings.sync()
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
        audio, failures = collect_audio(paths)
        added = 0
        for path in audio:
            full = os.path.abspath(path)
            if full in self.files:
                continue
            self.files.append(full)
            self.file_list.addItem(QListWidgetItem(""))
            added += 1
        self._refresh_list()
        self._refresh_table()
        self._update_buttons()
        self.empty_label.setVisible(not self.files)
        if added:
            # Remember where the files came from, for next time.
            folder = os.path.dirname(self.files[-1])
            self.settings.last_folder = folder
            try:
                self.settings.save()
            except OSError:
                pass
            # Counts only: the GUI logs no user-supplied text.
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
            else:
                bpm = result.get("bpm")
                key = result.get("key")
                bpm_text = ("%.1f BPM" % bpm) if bpm is not None \
                    else "BPM unknown"
                key_text = key if key is not None else "key unknown"
                item.setText("%s: %s, %s" % (name, bpm_text,
                                             key_text))

    def _refresh_table(self):
        """Rebuild the results table from the file list and the
        results so far. Files with no result yet get a row of
        plain dashes, so the table always matches the file list.
        Nothing is selected after a refresh."""
        self.results_table.setRowCount(len(self.files))
        for row, path in enumerate(self.files):
            result = self._results.get(path)
            name = os.path.basename(path)
            if result is None:
                cells = (name, "-", "-", "-", "-")
                tip = None
            else:
                cells = (name, format_bpm(result),
                         format_key(result),
                         format_confidence(result),
                         format_duration(result))
                tip = result.get("error")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags()
                              & ~Qt.ItemIsEditable)
                if column == 0 and tip:
                    item.setToolTip(tip)
                self.results_table.setItem(row, column, item)
        self.results_table.clearSelection()
        self.results_table.setCurrentCell(-1, -1)

    def _update_buttons(self):
        running = self._worker is not None
        self.analyze_button.setEnabled(bool(self.files)
                                       and not running)
        self.export_button.setEnabled(bool(self._results)
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

    # -- analyze ------------------------------------------------------
    def _on_analyze(self):
        if not self.files or self._worker is not None:
            return
        self._run_mode = "analyze"
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("analyze started for %d file(s)"
                           % len(self.files))
        self._worker = CliWorker("analyze",
                                 analyze_argv(list(self.files)),
                                 parent=self)
        self._worker.done.connect(self._on_analyze_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.cancelled.connect(self._on_run_cancelled)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self._set_busy(True, "Analyzing...")
        self._worker.start()

    def _on_analyze_done(self, results, exit_code):
        self._worker = None
        self._run_mode = None
        errors = 0
        unknown_bpm = 0
        for result in results:
            self._results[result["path"]] = result
            if result.get("error"):
                errors += 1
            elif result.get("bpm") is None:
                unknown_bpm += 1
        # After the results land: _set_busy refreshes the buttons,
        # and Export is only enabled once results exist.
        self._set_busy(False)
        # Counts and the exit code only: no user-supplied text.
        self.logger.action(
            "analyze finished: exit %d, %d file(s), %d error(s)"
            % (exit_code, len(results), errors))
        self._refresh_list()
        self._refresh_table()
        parts = ["Analyzed %d file(s)" % len(results)]
        if unknown_bpm:
            parts.append("%d with no beat found"
                         % unknown_bpm)
        if errors:
            parts.append("%d could not be read" % errors)
        self.status_bar.showMessage(": ".join(parts)
                                    if len(parts) > 1
                                    else parts[0])

    # -- export -------------------------------------------------------
    def _default_export_path(self):
        """The export dialog's starting path: next to the first
        analyzed file, or in the last folder used."""
        folder = None
        for path in self.files:
            if path in self._results:
                folder = os.path.dirname(path)
                break
        if folder is None:
            folder = self.settings.last_folder or os.path.expanduser(
                "~")
        return os.path.join(folder, "song-key-bpm.csv")

    def export_results(self, out_path):
        """Export the current results to this CSV path. Returns
        True when the export run started, False when there is
        nothing to export or a run is already going."""
        if not self._results or self._worker is not None:
            return False
        ordered = [self._results[path] for path in self.files
                   if path in self._results]
        fd, json_path = tempfile.mkstemp(prefix="songkey-results-",
                                         suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(ordered, fh, indent=2)
                fh.write("\n")
        except OSError:
            try:
                os.unlink(json_path)
            except OSError:
                pass
            self.status_bar.showMessage(
                "Could not write the export. Try again.")
            return False
        self._run_mode = "export"
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("export started for %d result(s)"
                           % len(ordered))
        self._worker = CliWorker(
            "export", export_argv(json_path, out_path),
            out_path=out_path, cleanup_path=json_path, parent=self)
        self._worker.done.connect(self._on_export_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.cancelled.connect(self._on_run_cancelled)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self._set_busy(True, "Exporting...")
        self._worker.start()
        return True

    def _on_export_done(self, out_path, exit_code):
        self._worker = None
        self._run_mode = None
        self._set_busy(False)
        count = len([p for p in self.files if p in self._results])
        # The count and the exit code only: the path may hold
        # user-supplied text.
        self.logger.action("export finished: exit %d, %d result(s)"
                           % (exit_code, count))
        self.status_bar.showMessage(
            "Exported %d result(s) to %s"
            % (count, os.path.basename(out_path)))

    # -- run lifecycle ------------------------------------------------
    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    def _on_run_failed(self, message, exit_code):
        mode = self._run_mode
        self._worker = None
        self._run_mode = None
        self._set_busy(False, "Ready")
        self.status_bar.showMessage(message)
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
        start = self.settings.last_folder or os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", start,
            "Audio files (*.wav *.mp3 *.flac *.ogg *.oga);;"
            "All files (*)")
        if paths:
            self.add_files(paths)

    def _on_export(self):
        if not self._results or self._worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export results", self._default_export_path(),
            "CSV files (*.csv)")
        if path:
            self.export_results(path)

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
            if any(os.path.isfile(u) or os.path.isdir(u)
                   for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        files = [p for p in paths
                 if os.path.isfile(p) or os.path.isdir(p)]
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
        print("Song Key BPM is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
