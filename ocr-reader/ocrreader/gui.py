"""Qt GUI for OCR Reader. A THIN viewer: it does no OCR itself.
It runs `ocr-read --json` and `ocr-clean --json` as subprocesses
in a worker thread, parses the JSON they print, and displays the
text. The window and the terminal always agree, because they run
the same commands.

Import rule (enforced by a test that parses this file with ast):
this module must NOT import ocrreader.engine, ocrreader.clean,
ocrreader.cli, PIL, or pytesseract. It imports Qt,
ocrreader.settings, ocrreader.logsetup (for make_logger), and the
standard library only. The GUI logs no user-supplied text, only
counts and exit codes.

One main window: a file list on the left, the extracted text on
the right. Drop image or PDF files in, press Read, read the text;
press Clean to tidy the whitespace in the text shown. Runs happen in a
worker thread; the window never blocks. Single instance via
QLockFile. Geometry is remembered between runs.

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
                               QTextEdit, QVBoxLayout, QWidget)

from .logsetup import make_logger
from .settings import Settings, data_dir

APP_DISPLAY_NAME = "OCR Reader"
DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 650
ORG_NAME = "BrokeNBored"
QSETTINGS_APP_NAME = "OCRReader"

# Files the window accepts, by extension: the image formats the
# reader handles, plus PDF (the engine reads PDFs page by page
# through pdftoppm). This is a copy of what the engine accepts:
# the GUI must not import the engine, so the list lives here too.
# If the engine ever gains a format, add it here as well.
READABLE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff",
                       ".bmp", ".gif", ".webp", ".pdf")

# The honest caveat, in plain words. It also appears as a label in
# the window and in the How to Use window. Kept word for word with
# the README's copy; the GUI cannot import anything that holds it,
# so the text lives here too. If the wording ever changes, change
# both copies.
CAVEAT_TEXT = (
    "OCR is approximate: handwriting and low-contrast images "
    "read poorly. Check the text before you use it."
)

CLEAN_TIP = (
    "Tidy the whitespace in the text shown. Clean only tidies "
    "whitespace, it never rewrites words."
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
QPushButton#readButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#readButton:hover { background-color: #a06f22; }
QPushButton#readButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QTextEdit, QListWidget { background-color: #1a1d21;
    border: 1px solid #3a3e44; border-radius: 4px; padding: 3px;
    color: #e8e8e8; }
QListWidget::item:selected {
    background-color: #3d4249; }
QLabel#caveatLabel { color: #b0b0b0; font-style: italic; }
QLabel#busyLight { border-radius: 6px; min-width: 12px; max-width: 12px;
    min-height: 12px; max-height: 12px; background-color: #555555; }
QLabel#busyLight[busy="true"] { background-color: #e8a33d; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
"""

# The chain tools, by wrapper name. The subcommand is the part
# after "ocr-": ocr-read runs `python -m ocrreader read` when no
# installed wrapper is on PATH.
_SUBCOMMANDS = {"ocr-read": "read", "ocr-clean": "clean"}


def package_root():
    """The folder holding the ocrreader package: the subprocess runs
    there so `python -m ocrreader` finds the package."""
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


def cli_command(name):
    """The command prefix for one chain tool: the installed wrapper
    when it is on PATH, else this Python running
    `python -m ocrreader <subcommand>` from the tree. The PATH
    lookup is also what lets the tests put a stub tool on PATH that
    prints canned JSON, to check the window's parsing without
    waiting on real OCR."""
    wrapper = shutil.which(name)
    if wrapper:
        return [wrapper]
    return [sys.executable, "-m", "ocrreader", _SUBCOMMANDS[name]]


def read_argv(paths, language="eng"):
    """Full argv for one read run over these paths, in this language."""
    return (cli_command("ocr-read") + ["--json", "--lang", language]
            + list(paths))


def clean_argv(text_path):
    """Full argv for one clean run over this text file."""
    return cli_command("ocr-clean") + [text_path, "--json"]


def collect_inputs(paths):
    """Expand files and folders into a sorted list of readable
    paths (images and PDFs).

    Folders are walked recursively; only supported files are
    picked up. Returns (files, failures): failures holds
    (path, reason) for paths that were not usable.
    """
    files = []
    failures = []
    for path in paths:
        if os.path.isfile(path):
            if path.lower().endswith(READABLE_EXTENSIONS):
                files.append(path)
            else:
                failures.append((path, "not an image or PDF file"))
        elif os.path.isdir(path):
            found = []
            for root, dirs, names in os.walk(path):
                dirs.sort()
                for name in sorted(names):
                    if name.lower().endswith(READABLE_EXTENSIONS):
                        found.append(os.path.join(root, name))
            if not found:
                failures.append((path,
                                 "no image or PDF files in it"))
            files.extend(found)
        else:
            failures.append((path, "not a file"))
    return files, failures


def word_count(text):
    """Words in a text, for the file list verdicts."""
    return len(text.split())


class CliWorker(QThread):
    """Run one CLI command in a worker thread. Never blocks the UI.

    mode "read": argv prints a JSON list of result dicts on
    stdout; done carries that list plus the CLI exit code. A
    nonzero exit is not a failure on its own: read exits 1 when
    no file could be read, and still prints good JSON.

    mode "clean": argv prints a JSON object with "text" and
    "changes" on stdout; done carries that object plus the CLI
    exit code.

    failed carries a display message plus the exit code (-1 when
    the process never started). The message is the CLI's own
    plain last line of stderr, never a traceback. Cancel kills
    the subprocess outright (SIGKILL), it does not just abandon
    it. cleanup_path, when given, is a temp file removed when
    the run ends however it ends.
    """

    done = Signal(object, int)
    failed = Signal(str, int)
    cancelled = Signal()

    def __init__(self, mode, argv, cleanup_path=None, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._argv = list(argv)
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
        try:
            payload = json.loads(stdout)
        except ValueError:
            detail = stderr.strip().splitlines()
            detail = detail[-1] if detail else "no output"
            self.failed.emit(
                "The %s failed (exit %d): %s"
                % (self._mode, exit_code, detail[:200]),
                exit_code)
            self._cleanup()
            return
        if self._mode == "read":
            if not isinstance(payload, list):
                self.failed.emit(
                    "The read printed unexpected output "
                    "(exit %d)" % exit_code,
                    exit_code)
                self._cleanup()
                return
        else:
            if not isinstance(payload, dict) or "text" not in payload:
                self.failed.emit(
                    "The clean printed unexpected output "
                    "(exit %d)" % exit_code,
                    exit_code)
                self._cleanup()
                return
        self.done.emit(payload, exit_code)
        self._cleanup()

    def _cleanup(self):
        if self._cleanup_path:
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass


HOW_TO_USE_TEXT = """How to use OCR Reader

1. Add files: drag image files (PNG, JPEG, TIFF, BMP, GIF, WebP)
   or PDF files onto the window, or use File, Add files. You can
   add several at once, or drop a whole folder: every image or
   PDF file under it is added.

2. Press Read. Each file is read and its text appears on the
   right. Select a file in the list to see its text. A PDF is
   read page by page, with a page marker between pages. A file
   the reader cannot read says so in the list, in plain words.

3. Press Clean to tidy the text shown: it joins wrapped lines
   and tidies whitespace. Clean only tidies whitespace, it
   never rewrites words.

4. Copy copies the text shown. Save writes it to a text file
   you pick, next to the picture by default.

5. Press Cancel any time to stop a run in progress.

6. Debug report: File, Generate debug report writes a file you
   can send to broke.n.bored.studio@gmail.com if something breaks.

%s

The same work runs from the terminal, one step at a time:
ocr-read reads pictures, ocr-clean tidies a text file,
ocr-reader opens this window. Run any of them with --help.
""" % CAVEAT_TEXT


class HowToUseWindow(QWidget):
    """The built-in How to Use index (U22). Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use OCR Reader")
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
        # store: settings.py holds the last folder and the
        # language only. Tests pass their own QSettings backend.
        if qsettings is not None:
            self._qsettings = qsettings
        else:
            self._qsettings = QSettings(ORG_NAME, QSETTINGS_APP_NAME)
        self.files = []           # absolute paths, in list order
        self._results = {}        # path -> last result dict
        self._current_path = None  # path whose text is shown
        self._worker = None
        self._run_mode = None     # "read" or "clean", while running
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
            "No files yet. Add image or PDF files or drop them here.",
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
        self.read_button = QPushButton("Read", left)
        self.read_button.setObjectName("readButton")
        self.read_button.clicked.connect(self._on_read)
        button_row.addWidget(self.read_button)
        self.cancel_button = QPushButton("Cancel", left)
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_button)
        left_layout.addLayout(button_row)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.text_source_label = QLabel("No text yet.", right)
        self.text_source_label.setObjectName("textSourceLabel")
        right_layout.addWidget(self.text_source_label)
        self.text_pane = QTextEdit(right)
        self.text_pane.setObjectName("textPane")
        self.text_pane.setReadOnly(True)
        self.text_pane.setPlaceholderText(
            "Read text appears here. Add image files, "
            "then press Read.")
        right_layout.addWidget(self.text_pane, 1)
        text_button_row = QHBoxLayout()
        self.clean_button = QPushButton("Clean", right)
        self.clean_button.setObjectName("cleanButton")
        self.clean_button.setToolTip(CLEAN_TIP)
        self.clean_button.clicked.connect(self._on_clean)
        text_button_row.addWidget(self.clean_button)
        self.copy_button = QPushButton("Copy", right)
        self.copy_button.setObjectName("copyButton")
        self.copy_button.clicked.connect(self._on_copy)
        text_button_row.addWidget(self.copy_button)
        self.save_button = QPushButton("Save", right)
        self.save_button.setObjectName("saveButton")
        self.save_button.clicked.connect(self._on_save)
        text_button_row.addWidget(self.save_button)
        text_button_row.addStretch(1)
        right_layout.addLayout(text_button_row)
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
        save_action = QAction("Save text", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._on_save)
        file_menu.addAction(save_action)
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
            return
        self._user_selecting = False
        if row == -1:
            return
        self._current_path = self.files[row]
        self._show_current()
        self._update_buttons()

    # -- file list ----------------------------------------------------
    def add_files(self, paths):
        """Add files to the list. Returns (added, failures)."""
        inputs, failures = collect_inputs(paths)
        added = 0
        for path in inputs:
            full = os.path.abspath(path)
            if full in self.files:
                continue
            self.files.append(full)
            self.file_list.addItem(QListWidgetItem(""))
            added += 1
        self._refresh_list()
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
                words = word_count(result.get("text") or "")
                pages = result.get("pages")
                if pages and pages > 1:
                    item.setText("%s: %d pages, %d words"
                                 % (name, pages, words))
                else:
                    item.setText("%s: %d words" % (name, words))

    def _displayed_text(self):
        """The text the pane is showing: the current file's text,
        or "" when there is none (no file, an error, empty)."""
        if self._current_path is None:
            return ""
        result = self._results.get(self._current_path)
        if result is None or result.get("error"):
            return ""
        return result.get("text") or ""

    def _show_current(self):
        """Show the current file's text in the pane."""
        if self._current_path is None:
            self.text_source_label.setText("No text yet.")
            self.text_pane.setPlainText("")
            return
        name = os.path.basename(self._current_path)
        result = self._results.get(self._current_path)
        if result is None:
            self.text_source_label.setText(
                "Text from: %s (not read yet)" % name)
            self.text_pane.setPlainText("")
        elif result.get("error"):
            # The CLI's plain error, never a traceback.
            self.text_source_label.setText(
                "Text from: %s (could not read)" % name)
            self.text_pane.setPlainText(
                "Could not read this file.\n\n%s"
                % result["error"])
        else:
            self.text_source_label.setText("Text from: %s" % name)
            self.text_pane.setPlainText(result.get("text") or "")

    def _update_buttons(self):
        running = self._worker is not None
        has_text = self._displayed_text() != ""
        self.read_button.setEnabled(bool(self.files)
                                    and not running)
        self.clean_button.setEnabled(has_text and not running)
        self.copy_button.setEnabled(has_text)
        self.save_button.setEnabled(has_text)
        self.add_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _set_busy(self, busy, message=None):
        self.busy_light.setProperty("busy", busy)
        self.busy_light.style().unpolish(self.busy_light)
        self.busy_light.style().polish(self.busy_light)
        if message is not None:
            self.status_bar.showMessage(message)
        self._update_buttons()

    # -- read ---------------------------------------------------------
    def _on_read(self):
        if not self.files or self._worker is not None:
            return
        self._run_mode = "read"
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("read started for %d file(s)"
                           % len(self.files))
        self._worker = CliWorker("read",
                                 read_argv(list(self.files),
                                           self.settings.language),
                                 parent=self)
        self._worker.done.connect(self._on_read_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.cancelled.connect(self._on_run_cancelled)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self._set_busy(True, "Reading...")
        self._worker.start()

    def _on_read_done(self, results, exit_code):
        self._worker = None
        self._run_mode = None
        errors = 0
        words = 0
        for index, result in enumerate(results):
            # The CLI reports each file's path; fall back to the
            # file order when a result carries none. Paths are
            # normalized to absolute, so a CLI that echoes a
            # relative path still matches the file list.
            path = result.get("path")
            if not path and index < len(self.files):
                path = self.files[index]
            if not path:
                continue
            self._results[os.path.abspath(path)] = result
            if result.get("error"):
                errors += 1
            else:
                words += word_count(result.get("text") or "")
        # After the results land: show the first file's text when
        # nothing is showing yet. The list row stays unselected:
        # U6 says select nothing by default.
        if self._current_path is None and results:
            first = results[0].get("path")
            if first:
                self._current_path = os.path.abspath(first)
            elif self.files:
                self._current_path = self.files[0]
        self._set_busy(False)
        # Counts and the exit code only: no user-supplied text.
        self.logger.action(
            "read finished: exit %d, %d file(s), %d error(s)"
            % (exit_code, len(results), errors))
        self._refresh_list()
        self._show_current()
        self._update_buttons()
        parts = ["Read %d file(s), %d words"
                 % (len(results), words)]
        if errors:
            parts.append("%d could not be read" % errors)
        self.status_bar.showMessage(": ".join(parts)
                                    if len(parts) > 1
                                    else parts[0])

    # -- clean --------------------------------------------------------
    def _on_clean(self):
        text = self._displayed_text()
        if not text or self._current_path is None \
                or self._worker is not None:
            return
        # Clean takes a file: write the shown text to a temp file,
        # never into the user's folders. The worker removes it
        # when the run ends, however it ends.
        fd, tmp_path = tempfile.mkstemp(prefix="ocrreader-clean-",
                                        suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            self.status_bar.showMessage(
                "Could not write the text to clean. Try again.")
            return
        self._run_mode = "clean"
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("clean started for %d word(s)"
                           % word_count(text))
        self._worker = CliWorker(
            "clean", clean_argv(tmp_path), cleanup_path=tmp_path,
            parent=self)
        self._worker.done.connect(self._on_clean_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.cancelled.connect(self._on_run_cancelled)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.cancelled.connect(self._worker.deleteLater)
        self._set_busy(True, "Cleaning...")
        self._worker.start()

    def _on_clean_done(self, payload, exit_code):
        self._worker = None
        self._run_mode = None
        self._set_busy(False)
        cleaned = payload.get("text", "")
        changes = payload.get("changes") or []
        if self._current_path is not None \
                and self._current_path in self._results:
            self._results[self._current_path]["text"] = cleaned
        # Counts and the exit code only: the changes list can
        # hold user-supplied text.
        self.logger.action("clean finished: exit %d, %d change(s)"
                           % (exit_code, len(changes)))
        self._refresh_list()
        self._show_current()
        self._update_buttons()
        if changes:
            self.status_bar.showMessage(
                "Cleaned: %s" % "; ".join(changes))
        else:
            self.status_bar.showMessage(
                "Cleaned: nothing needed changing")

    # -- copy / save --------------------------------------------------
    def _on_copy(self):
        text = self._displayed_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.status_bar.showMessage("Copied the text")

    def _default_save_path(self):
        """The save dialog's starting path: next to the current
        picture, named after it, or in the last folder used."""
        folder = None
        stem = "ocr-text"
        if self._current_path is not None:
            folder = os.path.dirname(self._current_path)
            stem = os.path.splitext(
                os.path.basename(self._current_path))[0]
        if folder is None:
            folder = self.settings.last_folder or os.path.expanduser(
                "~")
        return os.path.join(folder, stem + ".txt")

    def save_text(self, out_path):
        """Write the shown text to this path. Returns True when
        the write happened, False when there is no text to save
        or the write failed."""
        text = self._displayed_text()
        if not text:
            return False
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            self.status_bar.showMessage(
                "Could not write the file. Try again.")
            return False
        # The count only: the path may hold user-supplied text.
        self.logger.action("saved %d word(s)"
                           % word_count(text))
        self.status_bar.showMessage(
            "Saved the text to %s" % os.path.basename(out_path))
        return True

    def _on_save(self):
        if not self._displayed_text():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save text", self._default_save_path(),
            "Text files (*.txt)")
        if path:
            self.save_text(path)

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
            "Image and PDF files (*.png *.jpg *.jpeg *.tif *.tiff "
            "*.bmp *.gif *.webp *.pdf);;"
            "All files (*)")
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
        print("OCR Reader is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
