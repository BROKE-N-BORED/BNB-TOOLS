"""Qt GUI for AppImage Runner. A THIN viewer: it does no work
itself. It runs `appimagehelper-cli launch --json <file>` as a
subprocess in a worker thread, parses the JSON it prints, and
shows the result. The window and the terminal always agree,
because they run the same command.

Import rule (enforced by a test that parses this file with ast):
this module must NOT import appimagehelper.core or
appimagehelper.cli. It imports Qt, appimagehelper.settings,
appimagehelper.logsetup (for make_logger), and the standard
library only. The GUI logs no user-supplied text, only counts
and exit codes.

One main window: pick a file (or drop one on the window), press
Run it. The help note carries the phone-first checklist from the
incident that made this tool: an Android File Transfer AppImage
that could not see the phone because the phone was plugged in
after the app opened.

Visible text rules (design rules U11, U33): no em-dashes
anywhere, no bare & in any label. Keep it that way when editing
strings. Dialogs are sized to content: the window opens at its
size hint or bigger, never smaller (the FYRN Settings window
opened 560x220 against 527 px of content and clipped every
label; that is the failure this rule exists to prevent).
"""

import json
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import (QByteArray, QLockFile, QSettings,
                            Qt, QThread, Signal)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog,
                               QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton,
                               QStatusBar, QTextEdit, QVBoxLayout,
                               QWidget)

from .logsetup import make_logger
from .settings import Settings, data_dir

APP_DISPLAY_NAME = "AppImage Runner"
# The defaults must exceed the window's size hint (644 px wide
# in the test env): opening smaller than the content is the
# FYRN flaw the size tests pin against.
DEFAULT_WIDTH = 680
DEFAULT_HEIGHT = 540
ORG_NAME = "BrokeNBored"
QSETTINGS_APP_NAME = "AppImageRunner"

# The phone-first checklist, in plain words. It also appears in
# the How to Use window and in the README. Kept word for word in
# all three; the GUI cannot import anything that holds it, so the
# text lives here too. If the wording ever changes, change all
# three copies.
PHONE_FIRST_TEXT = (
    "Phone app? Plug the phone in FIRST:\n"
    "1. Plug the phone into the PC with the USB cable and "
    "unlock it.\n"
    "2. Pull down the phone notifications, tap the USB notice, "
    "and pick File Transfer.\n"
    "3. Open the app AFTER the phone is set to File Transfer, "
    "or the app will not see it.\n"
    "4. If the phone still does not show up, try another USB "
    "port or cable. Some cables only charge and cannot move "
    "files."
)

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #23262b; color: #e8e8e8;
    font-size: 13px; }
QPushButton { background-color: #33373d; border: 1px solid #4a4f56;
    border-radius: 5px; padding: 4px 12px; color: #e8e8e8; }
QPushButton:hover { background-color: #3d4249; }
QPushButton:pressed { background-color: #2b2e33; }
QPushButton:disabled { color: #777777; }
QPushButton:focus, QTextEdit:focus {
    border: 2px solid #e8a33d; outline: none; }
QPushButton#runButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#runButton:hover { background-color: #a06f22; }
QPushButton#runButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QTextEdit { background-color: #1a1d21;
    border: 1px solid #3a3e44; border-radius: 4px; padding: 3px;
    color: #e8e8e8; }
QLabel#helpNote { color: #c8c8c8; background-color: #1a1d21;
    border: 1px solid #3a3e44; border-radius: 4px; padding: 8px; }
QLabel#busyLight { border-radius: 6px; min-width: 12px; max-width: 12px;
    min-height: 12px; max-height: 12px; background-color: #555555; }
QLabel#busyLight[busy="true"] { background-color: #e8a33d; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
"""


def package_root():
    """The folder holding the appimagehelper package: the
    subprocess runs there so `python -m appimagehelper` finds
    the package."""
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


def cli_command():
    """The command prefix for the full CLI: the installed wrapper
    when it is on PATH, else this Python running
    `python -m appimagehelper` from the tree. The PATH lookup is
    also what lets the tests put a stub tool on PATH that prints
    canned JSON, to check the window's parsing without running a
    real AppImage."""
    wrapper = shutil.which("appimagehelper-cli")
    if wrapper:
        return [wrapper]
    return [sys.executable, "-m", "appimagehelper"]


def launch_argv(path):
    """Full argv for one launch run over this file."""
    return cli_command() + ["launch", "--json", path]


def is_appimage_name(path):
    """True when the file name ends in .AppImage (any case).

    A name check only, never a gate: the GUI must not import the
    core module, so the check lives here too. If the core ever
    changes what counts, change both copies.
    """
    return os.path.basename(path).lower().endswith(".appimage")


class CliWorker(QThread):
    """Run one CLI command in a worker thread. Never blocks the UI.

    argv prints a JSON object on stdout; done carries that object
    plus the CLI exit code. A nonzero exit is not a failure on its
    own: launch exits 1 with good JSON carrying the plain error.

    failed carries a display message plus the exit code (-1 when
    the process never started). The message is the CLI's own
    plain last line of stderr, never a traceback.
    """

    done = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self, argv, parent=None):
        super().__init__(parent)
        self._argv = list(argv)
        self._proc = None

    def run(self):
        root = package_root()
        env = dict(os.environ)
        path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = root if not path else root + os.pathsep + path
        try:
            self._proc = subprocess.Popen(
                self._argv, cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            self.failed.emit("Could not start the command: %s"
                             % exc, -1)
            return
        try:
            stdout, stderr = self._proc.communicate()
        except Exception as exc:  # never let the thread die silently
            self.failed.emit("The command failed: %s" % exc, -1)
            return
        exit_code = self._proc.returncode
        try:
            payload = json.loads(stdout)
        except ValueError:
            detail = stderr.strip().splitlines()
            detail = detail[-1] if detail else "no output"
            self.failed.emit(
                "The launch failed (exit %d): %s"
                % (exit_code, detail[:200]),
                exit_code)
            return
        if not isinstance(payload, dict):
            self.failed.emit(
                "The launch printed unexpected output "
                "(exit %d)" % exit_code,
                exit_code)
            return
        self.done.emit(payload, exit_code)


HOW_TO_USE_TEXT = """How to use AppImage Runner

1. Pick a file: press Pick a file and choose the AppImage, or
   drag the AppImage onto the window. A file that does not end
   in .AppImage still works: the tool tries it anyway and says
   so in plain words.

2. Press Run it. The tool makes the file runnable (the same as
   ticking "Allow executing file as program" in the file
   manager) and then runs it. The app opens in its own window
   and keeps running after this tool closes.

3. If the app stops right away, the status line says so in
   plain words. The usual cause is a missing library: an
   AppImage needs the FUSE library to start. The debug report
   (File, Generate debug report) says whether FUSE is on this
   computer.

%s

The same work runs from the terminal, one step at a time:
appimage-make-runnable sets the exec bit, appimagehelper-cli
launch makes it runnable and runs it, appimage-run opens this
window. Run any of them with --help.
""" % PHONE_FIRST_TEXT


class HowToUseWindow(QWidget):
    """The built-in How to Use index (U22). Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use AppImage Runner")
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
        # store: settings.py holds the last folder only. Tests
        # pass their own QSettings backend.
        if qsettings is not None:
            self._qsettings = qsettings
        else:
            self._qsettings = QSettings(ORG_NAME, QSETTINGS_APP_NAME)
        self.picked_path = None
        self._worker = None
        self._how_to_use = None
        self._build_ui()
        self._restore_geometry()
        self._update_buttons()

    # -- construction -------------------------------------------------
    def _build_ui(self):
        self._build_menus()
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.instruction_label = QLabel(
            "Drop an AppImage here, or pick one, then press "
            "Run it.", central)
        self.instruction_label.setObjectName("instructionLabel")
        self.instruction_label.setWordWrap(True)
        root.addWidget(self.instruction_label)

        file_row = QHBoxLayout()
        self.file_label = QLabel("No file picked yet.", central)
        self.file_label.setObjectName("fileLabel")
        self.file_label.setWordWrap(True)
        file_row.addWidget(self.file_label, 1)
        self.pick_button = QPushButton("Pick a file", central)
        self.pick_button.setObjectName("pickButton")
        self.pick_button.clicked.connect(self._on_pick_file)
        file_row.addWidget(self.pick_button)
        root.addLayout(file_row)

        self.run_button = QPushButton("Run it", central)
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._on_run)
        root.addWidget(self.run_button)

        self.status_label = QLabel("Ready.", central)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.help_note = QLabel(PHONE_FIRST_TEXT, central)
        self.help_note.setObjectName("helpNote")
        self.help_note.setWordWrap(True)
        self.help_note.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self.help_note, 1)

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
        pick_action = QAction("Pick a file", self)
        pick_action.setShortcut(QKeySequence.Open)
        pick_action.triggered.connect(self._on_pick_file)
        file_menu.addAction(pick_action)
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
        self._qsettings.setValue(
            "window_geometry", QByteArray(self.saveGeometry()))
        self._qsettings.sync()
        super().closeEvent(event)

    # -- file picking -------------------------------------------------
    def pick_file(self, path):
        """Pick this file to run. Returns True when the file is
        usable, False when it is not a file (plain words in the
        status line)."""
        if not os.path.isfile(path):
            self.status_label.setText(
                "That is not a file: %s"
                % os.path.basename(path))
            self.status_bar.showMessage(
                "That is not a file.")
            return False
        self.picked_path = os.path.abspath(path)
        name = os.path.basename(self.picked_path)
        self.file_label.setText("File: %s" % name)
        if is_appimage_name(self.picked_path):
            self.status_label.setText("Ready to run %s." % name)
            self.status_bar.showMessage("Ready to run")
        else:
            self.status_label.setText(
                "%s does not look like an AppImage, but I will "
                "try it anyway." % name)
            self.status_bar.showMessage("Ready to run")
        # Remember where the file came from, for next time.
        self.settings.last_folder = os.path.dirname(
            self.picked_path)
        try:
            self.settings.save()
        except OSError:
            pass
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("picked a file")
        self._update_buttons()
        return True

    def _update_buttons(self):
        running = self._worker is not None
        self.run_button.setEnabled(self.picked_path is not None
                                   and not running)
        self.pick_button.setEnabled(not running)

    def _set_busy(self, busy, message=None):
        self.busy_light.setProperty("busy", busy)
        self.busy_light.style().unpolish(self.busy_light)
        self.busy_light.style().polish(self.busy_light)
        if message is not None:
            self.status_bar.showMessage(message)
        self._update_buttons()

    # -- run ----------------------------------------------------------
    def _on_run(self):
        if self.picked_path is None or self._worker is not None:
            return
        # Counts only: the GUI logs no user-supplied text.
        self.logger.action("launch started")
        self._worker = CliWorker(launch_argv(self.picked_path),
                                 parent=self)
        self._worker.done.connect(self._on_launch_done)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._set_busy(True, "Running...")
        self.status_label.setText("Starting it...")
        self._worker.start()

    def _on_launch_done(self, payload, exit_code):
        self._worker = None
        self._set_busy(False)
        error = payload.get("error")
        # Counts and the exit code only: no user-supplied text.
        self.logger.action(
            "launch finished: exit %d, error=%s"
            % (exit_code, bool(error)))
        name = os.path.basename(self.picked_path or "")
        if error:
            self.status_label.setText(error)
            self.status_bar.showMessage("It did not start")
            return
        if payload.get("running"):
            if payload.get("made_runnable"):
                self.status_label.setText(
                    "Made %s runnable, and it is running now."
                    % name)
            else:
                self.status_label.setText(
                    "%s is running now." % name)
            self.status_bar.showMessage("Running")
        elif payload.get("finished"):
            self.status_label.setText(
                "%s ran and finished." % name)
            self.status_bar.showMessage("Finished")
        else:
            self.status_label.setText(
                "It started, but I could not tell whether it is "
                "still running.")
            self.status_bar.showMessage("Started")

    def _on_run_failed(self, message, exit_code):
        self._worker = None
        self._set_busy(False, "Ready")
        self.status_label.setText(message)
        self.status_bar.showMessage("It did not start")
        # The exit code only: the message may carry CLI stderr,
        # which can hold user-supplied text.
        self.logger.warning("launch failed: exit %d" % exit_code)

    # -- menus --------------------------------------------------------
    def _on_pick_file(self):
        start = self.settings.last_folder or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick an AppImage", start,
            "AppImage files (*.AppImage *.appimage);;"
            "All files (*)")
        if path:
            self.pick_file(path)

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
            self.pick_file(files[0])
        event.acceptProposedAction()


def run_gui():
    """Open the window. Returns the app exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("BrokeNBored")
    app.setStyleSheet(DARK_STYLESHEET)
    lock = try_single_instance()
    if lock is None:
        print("AppImage Runner is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
