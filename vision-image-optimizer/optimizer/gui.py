"""Qt GUI for Vision Image Optimizer: a THIN viewer (v0.2.0).

One main window, two zones: images and preview on the left, settings
and results on the right. The window looks and behaves like v0.1.0,
but it does NO shrinking and NO describing itself: every piece of
real work runs in a subprocess, in a worker thread, so the window
never blocks.

The chain, run as small commands (each also works on its own):

    vision-shrink photo.png            shrink one picture
    vision-describe photo-512w.jpg     describe one picture as given

The GUI drives the same modules the commands use:

    python -m optimizer.shrink <file> --json
    python -m optimizer.describe <file> --json
    python -m optimizer.cli cache-stats --json
    python -m optimizer.cli cache-clear

Optimize selected / Optimize all run the shrink subprocess and show
the result. Describe runs shrink first (which writes the optimized
copy to the normal output folder) and then describe on that copy,
and shows the text plus the measurements. Cancel kills the running
subprocess promptly; closing the window mid-run stops it too.

IMPORT BAN (hard rule, test-enforced in tests/test_packaging.py):
this module must NOT import optimizer.shrink, optimizer.describe,
optimizer.cache, optimizer.ollama, optimizer.cli, PIL, or urllib.
It may import Qt, optimizer.tokens, optimizer.settings,
optimizer.logsetup, optimizer (__version__), and the stdlib.

Visible text rules (design rules U11, U33): no em-dashes anywhere,
no bare & in any label. Keep it that way when editing strings.
"""

import json
import os
import re
import subprocess
import sys

from PySide6.QtCore import (QByteArray, QEvent, QLockFile, QRect, QSize,
                            Qt, QThread, QTimer, Signal)
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QRubberBand, QScrollArea,
                               QSizePolicy, QSpinBox, QSplitter,
                               QStatusBar, QTextEdit, QVBoxLayout,
                               QWidget)

from . import __version__
from .logsetup import make_logger
from .settings import (QUALITY_PRESETS, SIZE_PRESETS, Settings,
                       cache_dir)
from .tokens import (SUPPORTED_EXTENSIONS, clamp_crop,
                     describe_measurements, format_measurements,
                     human_size, target_size, vision_tokens)

APP_DISPLAY_NAME = "Vision Image Optimizer"
DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 650

# Honest caveat, shown in the window and the README in plain words.
CAVEAT_TEXT = ("Only the vision part shrinks about 14x. The whole "
               "turn does not get 14x faster.")

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #23262b; color: #e8e8e8;
    font-size: 13px; }
QGroupBox { border: 1px solid #3a3e44; border-radius: 6px;
    margin-top: 10px; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px;
    color: #c8c8c8; }
QPushButton { background-color: #33373d; border: 1px solid #4a4f56;
    border-radius: 5px; padding: 4px 12px; color: #e8e8e8; }
QPushButton:hover { background-color: #3d4249; }
QPushButton:pressed { background-color: #2b2e33; }
QPushButton:disabled { color: #777777; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QListWidget:focus, QTextEdit:focus {
    border: 2px solid #e8a33d; outline: none; }
QPushButton#describeButton { background-color: #8a5f1d;
    border-color: #e8a33d; }
QPushButton#describeButton:hover { background-color: #a06f22; }
QPushButton#describeButton:disabled { background-color: #33373d;
    border-color: #4a4f56; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
    background-color: #1a1d21; border: 1px solid #3a3e44;
    border-radius: 4px; padding: 3px; color: #e8e8e8; }
QListWidget::item:selected { background-color: #3d4249; }
QLabel#tokenLabel { font-size: 15px; font-weight: bold; }
QLabel#caveatLabel { color: #b0b0b0; font-style: italic; }
QLabel#busyLight { border-radius: 6px; min-width: 12px; max-width: 12px;
    min-height: 12px; max-height: 12px; background-color: #555555; }
QLabel#busyLight[busy="true"] { background-color: #e8a33d; }
QMenuBar, QMenu { background-color: #23262b; color: #e8e8e8; }
QMenu::item:selected { background-color: #3d4249; }
QStatusBar { background-color: #1a1d21; color: #c8c8c8; }
QScrollArea { border: none; }
"""


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


def tree_root():
    """The folder holding the optimizer package (the tree root).

    The subprocesses run with this on PYTHONPATH, so the package is
    importable from the source tree AND from the installed location.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def subprocess_env():
    """Environment for the worker subprocesses: the caller's env with
    the tree root first on PYTHONPATH."""
    env = dict(os.environ)
    root = tree_root()
    existing = env.get("PYTHONPATH", "")
    if existing:
        env["PYTHONPATH"] = root + os.pathsep + existing
    else:
        env["PYTHONPATH"] = root
    return env


def _last_line(text):
    """The last non-empty line: a plain error stays whole, a
    traceback collapses to its exception line."""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


class _SubprocessThread(QThread):
    """Base for workers that run optimizer modules as subprocesses.

    Cancel kills the running subprocess promptly (SIGKILL) and the
    run loop checks the flag between steps, so a cancelled chain
    stops at the next step boundary at the latest.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._proc = None

    def cancel(self):
        self._cancelled = True
        proc = self._proc
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except (OSError, ValueError):
                pass

    def _run_json(self, module, args):
        """Run [sys.executable, -m, module, *args], parse --json stdout.

        Returns (payload, error): exactly one is None. (None, None)
        means the run was cancelled.
        """
        cmd = [sys.executable, "-m", module] + args
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=subprocess_env(), text=True)
        except OSError as exc:
            return None, "Could not start %s: %s" % (module, exc)
        self._proc = proc
        if self._cancelled:
            # Cancel landed after the flag check but before the
            # process started: kill it instead of running it out.
            try:
                proc.kill()
            except OSError:
                pass
            proc.communicate()
            self._proc = None
            return None, None
        try:
            stdout, stderr = proc.communicate()
        finally:
            self._proc = None
        if self._cancelled:
            return None, None
        if proc.returncode != 0:
            message = _last_line(stderr)
            return None, message if message else "%s failed" % module
        try:
            return json.loads(stdout), None
        except ValueError:
            return None, "Could not read the result from %s" % module

    def _run_plain(self, module, args):
        """Run one module subprocess, return its stdout text.

        Returns (stdout, error): exactly one is None. (None, None)
        means the run was cancelled.
        """
        cmd = [sys.executable, "-m", module] + args
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=subprocess_env(), text=True)
        except OSError as exc:
            return None, "Could not start %s: %s" % (module, exc)
        self._proc = proc
        if self._cancelled:
            # Cancel landed after the flag check but before the
            # process started: kill it instead of running it out.
            try:
                proc.kill()
            except OSError:
                pass
            proc.communicate()
            self._proc = None
            return None, None
        try:
            stdout, stderr = proc.communicate()
        finally:
            self._proc = None
        if self._cancelled:
            return None, None
        if proc.returncode != 0:
            message = _last_line(stderr)
            return None, message if message else "%s failed" % module
        return stdout, None


class OptimizeWorker(_SubprocessThread):
    """Shrink one or more pictures via the shrink subprocess.

    done emits a list of (record, payload, error); a failed picture
    is recorded with its error and the rest still run, like v0.1.
    """

    done = Signal(object)
    cancelled = Signal()

    def __init__(self, jobs, parent=None):
        # jobs: [(record, shrink-args), ...]
        super().__init__(parent)
        self._jobs = jobs

    def run(self):
        try:
            results = []
            for record, args in self._jobs:
                if self._cancelled:
                    self.cancelled.emit()
                    return
                payload, error = self._run_json(
                    "optimizer.shrink", args)
                if self._cancelled:
                    self.cancelled.emit()
                    return
                results.append((record, payload, error))
            self.done.emit(results)
        except Exception as exc:  # never let the thread die silently
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.done.emit([(record, None,
                                 "Optimizing failed: %s" % exc)
                                for record, _ in self._jobs])


class DescribeWorker(_SubprocessThread):
    """Describe one picture: shrink subprocess first (writes the
    optimized copy to the normal output folder), then the describe
    subprocess on that copy.

    done emits {"shrink": shrink-payload, "describe": describe-payload}.
    """

    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, shrink_args, describe_args, parent=None):
        super().__init__(parent)
        self._shrink_args = shrink_args
        # describe_args: the option flags; the file path goes first
        # once the shrink step has produced it.
        self._describe_args = describe_args

    def run(self):
        try:
            shrink, error = self._run_json(
                "optimizer.shrink", self._shrink_args)
            if self._cancelled:
                self.cancelled.emit()
                return
            if error is not None:
                self.failed.emit(error)
                return
            desc, error = self._run_json(
                "optimizer.describe",
                [shrink["path"]] + self._describe_args)
            if self._cancelled:
                self.cancelled.emit()
                return
            if error is not None:
                self.failed.emit(error)
                return
            self.done.emit({"shrink": shrink, "describe": desc})
        except Exception as exc:  # never let the thread die silently
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit("Describing failed: %s" % exc)


class CliWorker(_SubprocessThread):
    """One optimizer.cli call: cache-stats --json or cache-clear.

    done emits the parsed JSON payload (cache-stats), the stdout
    text (cache-clear), or None when the call failed or was
    cancelled.
    """

    done = Signal(object)

    def __init__(self, args, want_json, parent=None):
        super().__init__(parent)
        self._args = args
        self._want_json = want_json

    def run(self):
        try:
            if self._want_json:
                payload, error = self._run_json("optimizer.cli",
                                                self._args)
                self.done.emit(payload if error is None else None)
            else:
                text, error = self._run_plain("optimizer.cli",
                                              self._args)
                self.done.emit(text if error is None else None)
        except Exception:  # never let the thread die silently
            self.done.emit(None)


class CropPreviewLabel(QLabel):
    """Preview that shows the picture and takes a rubber-band crop.

    cropChanged emits the selected box in original-picture pixels,
    or None for the full picture.
    """

    cropChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(380, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setText("Drop images here to start")
        self._pixmap = None
        self._orig_w = 0
        self._orig_h = 0
        self._display_rect = QRect()
        self._band = QRubberBand(QRubberBand.Rectangle, self)
        self._drag_start = None
        self._crop = None
        self._setting_crop = False

    def set_image(self, pixmap, orig_w, orig_h):
        self._pixmap = pixmap
        self._orig_w = orig_w
        self._orig_h = orig_h
        self._crop = None
        self._band.hide()
        self.setText("")
        self.update()

    def clear_image(self):
        self._pixmap = None
        self._orig_w = 0
        self._orig_h = 0
        self._crop = None
        self._band.hide()
        self.setText("Drop images here to start")
        self.update()

    def crop(self):
        return self._crop

    def set_crop(self, box):
        """Show a crop box (original-picture pixels) or None."""
        self._setting_crop = True
        self._crop = box
        if box is None or self._pixmap is None:
            self._band.hide()
        else:
            self._band.setGeometry(self._image_to_label_rect(box))
            self._band.show()
        self._setting_crop = False

    def _scaled_size(self):
        if self._pixmap is None:
            return QSize(0, 0)
        return self._pixmap.size().scaled(self.size(),
                                          Qt.KeepAspectRatio)

    def _display_rect_for(self):
        size = self._scaled_size()
        x = (self.width() - size.width()) // 2
        y = (self.height() - size.height()) // 2
        return QRect(x, y, size.width(), size.height())

    def _image_to_label_rect(self, box):
        rect = self._display_rect_for()
        if self._orig_w == 0:
            return QRect()
        sx = rect.width() / self._orig_w
        sy = rect.height() / self._orig_h
        x, y, w, h = box
        return QRect(int(rect.x() + x * sx), int(rect.y() + y * sy),
                     int(w * sx), int(h * sy))

    def _label_to_image_point(self, pos):
        rect = self._display_rect_for()
        if self._orig_w == 0 or rect.width() == 0:
            return (0, 0)
        sx = self._orig_w / rect.width()
        sy = self._orig_h / rect.height()
        x = int((pos.x() - rect.x()) * sx)
        y = int((pos.y() - rect.y()) * sy)
        return (max(0, min(self._orig_w - 1, x)),
                max(0, min(self._orig_h - 1, y)))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap is None:
            return
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        rect = self._display_rect_for()
        painter.drawPixmap(rect, self._pixmap)
        painter.end()
        self._display_rect = rect
        if self._crop is not None and not self._setting_crop:
            self._band.setGeometry(self._image_to_label_rect(
                self._crop))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._crop is not None:
            self._band.setGeometry(self._image_to_label_rect(
                self._crop))

    def mousePressEvent(self, event):
        if self._pixmap is None or event.button() != Qt.LeftButton:
            return
        self._drag_start = event.position().toPoint()
        self._band.setGeometry(QRect(event.position().toPoint(), QSize()))
        self._band.show()

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        self._band.setGeometry(
            QRect(self._drag_start, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event):
        if self._drag_start is None:
            return
        self._drag_start = None
        rect = self._band.geometry()
        if rect.width() < 4 or rect.height() < 4:
            self._band.hide()
            self._crop = None
            self.cropChanged.emit(None)
            return
        x1, y1 = self._label_to_image_point(rect.topLeft())
        x2, y2 = self._label_to_image_point(rect.bottomRight())
        box = clamp_crop((x1, y1, x2 - x1, y2 - y1),
                         self._orig_w, self._orig_h)
        self._crop = box
        if box is None:
            self._band.hide()
        self.cropChanged.emit(box)


HOW_TO_USE_TEXT = """How to use Vision Image Optimizer

1. Add pictures: drag image files onto the window, or use File, Add
   images. The list shows each picture with its vision tokens before
   and after shrinking.

2. Pick a size: 512w is the starting size. A 1920x1080 screenshot
   reads 2040 tokens; at 512 wide it reads 144. That is about 14x
   less vision work for the model.

3. Crop if you want: drag a box on the preview to keep only the part
   that matters, or type numbers in the crop boxes. Full image
   clears the crop.

4. Optimize: Optimize selected saves a shrunken copy next to the
   original, in an "optimized" folder. Your original is never
   changed or overwritten.

5. Describe: Describe saves the shrunken copy first, then asks the
   local model what is in that copy. A small model looks first; the
   careful model only wakes up if the small one cannot see enough.
   If Ollama is not running, describing waits but shrinking still
   works.

6. Cache: the same picture with the same settings is answered once.
   A cached answer is marked "from cache". Clear cache empties it.

7. Settings: size, quality, format, output folder, Ollama address,
   both models, and the prompt are all on the right. They are
   remembered between runs.

8. From a terminal: the same steps run as small commands that chain
   together. vision-shrink photo.png saves the shrunken copy, then
   vision-describe photo-512w.jpg describes it. Each command also
   works on its own.

9. Debug report: File, Generate debug report writes a file you can
   send to broke.n.bored.studio@gmail.com if something breaks.

Only the vision part shrinks about 14x. The whole turn does not get
14x faster.
"""


class HowToUseWindow(QWidget):
    """The built-in How to Use index (U22). Its own window."""

    def __init__(self, parent=None):
        # Qt.Window: a parented widget without this flag renders
        # embedded inside the main window instead of as its own
        # window.
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("How to Use Vision Image Optimizer")
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
    def __init__(self, settings=None, cache=None, logger=None,
                 ollama_client=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.settings = settings or Settings()
        # cache and ollama_client are accepted for the v0.1 call
        # shape but no longer used for work: the cache lives in
        # the shrink/describe subprocesses, and Ollama is reached
        # by the describe subprocess at the settings URL. Tests
        # point the window at a fake server by setting the
        # ollama_url setting.
        self.logger = logger or make_logger(self.settings)
        self.logger.install_crash_handler()
        self.images = []          # image record dicts, in list order
        self._worker = None       # OptimizeWorker or DescribeWorker
        self._stats_worker = None  # CliWorker for cache-stats
        self._stats_pending = False
        self._clear_worker = None  # CliWorker for cache-clear
        self._how_to_use = None
        self._syncing_crop = False
        self._build_ui()
        self._restore_geometry()
        self._refresh_cache_label()
        self._update_estimates()
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
            "No images yet. Add images or drop them here.", left)
        self.empty_label.setObjectName("emptyStateLabel")
        left_layout.addWidget(self.empty_label)
        self.image_list = QListWidget(left)
        self.image_list.setObjectName("imageList")
        # The list is a picker, not the workspace: cap it so the
        # preview gets the room.
        self.image_list.setMaximumHeight(140)
        self.image_list.currentRowChanged.connect(
            self._on_selection_changed)
        left_layout.addWidget(self.image_list)
        self.preview = CropPreviewLabel(left)
        self.preview.cropChanged.connect(self._on_crop_changed)
        left_layout.addWidget(self.preview, 1)

        crop_row = QHBoxLayout()
        crop_row.addWidget(QLabel("Crop X", left))
        self.crop_x = QSpinBox(left)
        self.crop_x.setObjectName("cropX")
        self.crop_x.setRange(0, 100000)
        crop_row.addWidget(self.crop_x)
        crop_row.addWidget(QLabel("Y", left))
        self.crop_y = QSpinBox(left)
        self.crop_y.setObjectName("cropY")
        self.crop_y.setRange(0, 100000)
        crop_row.addWidget(self.crop_y)
        crop_row.addWidget(QLabel("W", left))
        self.crop_w = QSpinBox(left)
        self.crop_w.setObjectName("cropW")
        self.crop_w.setRange(1, 100000)
        crop_row.addWidget(self.crop_w)
        crop_row.addWidget(QLabel("H", left))
        self.crop_h = QSpinBox(left)
        self.crop_h.setObjectName("cropH")
        self.crop_h.setRange(1, 100000)
        crop_row.addWidget(self.crop_h)
        self.full_image_button = QPushButton("Full image", left)
        self.full_image_button.setObjectName("fullImageButton")
        self.full_image_button.clicked.connect(self._on_full_image)
        crop_row.addWidget(self.full_image_button)
        left_layout.addLayout(crop_row)
        for spin in (self.crop_x, self.crop_y, self.crop_w,
                     self.crop_h):
            spin.valueChanged.connect(self._on_crop_spin_changed)

        right_scroll = QScrollArea(splitter)
        right_scroll.setWidgetResizable(True)
        self.right_scroll = right_scroll
        right = QWidget(right_scroll)
        right_scroll.setWidget(right)
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(2)
        right_layout.setContentsMargins(4, 4, 4, 4)

        settings_group = QGroupBox("Size and quality", right)
        settings_form = QFormLayout(settings_group)
        settings_form.setVerticalSpacing(3)
        self._settings_form = settings_form
        self.size_preset = QComboBox(settings_group)
        self.size_preset.setObjectName("sizePreset")
        self.size_preset.addItems(SIZE_PRESETS)
        self.size_preset.setCurrentText(
            self.settings.get("size_preset"))
        self.size_preset.currentTextChanged.connect(
            self._on_settings_changed)
        settings_form.addRow("Resize to", self.size_preset)
        self.custom_width = QSpinBox(settings_group)
        self.custom_width.setObjectName("customWidth")
        self.custom_width.setRange(16, 8192)
        self.custom_width.setValue(
            int(self.settings.get("custom_width")))
        self.custom_width.valueChanged.connect(
            self._on_settings_changed)
        settings_form.addRow("Custom width", self.custom_width)
        # The custom rows only appear when Custom is picked, so the
        # panel stays short enough to fit the window at 650 px tall.
        self._custom_width_row = settings_form.rowCount() - 1
        self.quality_preset = QComboBox(settings_group)
        self.quality_preset.setObjectName("qualityPreset")
        self.quality_preset.addItems(QUALITY_PRESETS)
        self.quality_preset.setCurrentText(
            self.settings.get("quality_preset"))
        self.quality_preset.currentTextChanged.connect(
            self._on_settings_changed)
        settings_form.addRow("JPEG quality", self.quality_preset)
        self.custom_quality = QSpinBox(settings_group)
        self.custom_quality.setObjectName("customQuality")
        self.custom_quality.setRange(1, 100)
        self.custom_quality.setValue(
            int(self.settings.get("custom_quality")))
        self.custom_quality.valueChanged.connect(
            self._on_settings_changed)
        settings_form.addRow("Custom quality", self.custom_quality)
        self._custom_quality_row = settings_form.rowCount() - 1
        self.format_combo = QComboBox(settings_group)
        self.format_combo.setObjectName("formatCombo")
        self.format_combo.addItems(("JPEG", "PNG"))
        self.format_combo.setCurrentText(
            self.settings.get("output_format"))
        self.format_combo.currentTextChanged.connect(
            self._on_settings_changed)
        settings_form.addRow("Save as", self.format_combo)
        folder_row = QHBoxLayout()
        self.output_folder = QLineEdit(settings_group)
        self.output_folder.setObjectName("outputFolderEdit")
        self.output_folder.setText(self.settings.get("output_folder"))
        self.output_folder.setPlaceholderText(
            "Next to the original picture")
        self.output_folder.editingFinished.connect(
            self._on_settings_changed)
        folder_row.addWidget(self.output_folder, 1)
        browse_button = QPushButton("Browse", settings_group)
        browse_button.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(browse_button)
        settings_form.addRow("Save copies to", folder_row)
        right_layout.addWidget(settings_group)

        self.token_label = QLabel("No image selected", right)
        self.token_label.setObjectName("tokenLabel")
        right_layout.addWidget(self.token_label)
        self.totals_label = QLabel("", right)
        self.totals_label.setObjectName("totalsLabel")
        right_layout.addWidget(self.totals_label)
        self.caveat_label = QLabel(CAVEAT_TEXT, right)
        self.caveat_label.setObjectName("caveatLabel")
        self.caveat_label.setWordWrap(True)
        right_layout.addWidget(self.caveat_label)

        optimize_row = QHBoxLayout()
        self.optimize_button = QPushButton("Optimize selected", right)
        self.optimize_button.setObjectName("optimizeButton")
        self.optimize_button.clicked.connect(self._on_optimize_selected)
        optimize_row.addWidget(self.optimize_button)
        self.optimize_all_button = QPushButton("Optimize all", right)
        self.optimize_all_button.setObjectName("optimizeAllButton")
        self.optimize_all_button.clicked.connect(self._on_optimize_all)
        optimize_row.addWidget(self.optimize_all_button)
        right_layout.addLayout(optimize_row)

        describe_group = QGroupBox("Describe with the local model",
                                   right)
        describe_form = QFormLayout(describe_group)
        describe_form.setVerticalSpacing(3)
        self.prompt_edit = QLineEdit(describe_group)
        self.prompt_edit.setObjectName("promptEdit")
        self.prompt_edit.setText(self.settings.get("prompt"))
        self.prompt_edit.setCursorPosition(0)
        self.prompt_edit.editingFinished.connect(
            self._on_settings_changed)
        describe_form.addRow("Ask the model", self.prompt_edit)
        self.fast_model_edit = QLineEdit(describe_group)
        self.fast_model_edit.setObjectName("fastModelEdit")
        self.fast_model_edit.setText(self.settings.get("fast_model"))
        self.fast_model_edit.editingFinished.connect(
            self._on_settings_changed)
        describe_form.addRow("Small model first",
                             self.fast_model_edit)
        self.smart_model_edit = QLineEdit(describe_group)
        self.smart_model_edit.setObjectName("smartModelEdit")
        self.smart_model_edit.setText(
            self.settings.get("smart_model"))
        self.smart_model_edit.editingFinished.connect(
            self._on_settings_changed)
        describe_form.addRow("Careful model second",
                             self.smart_model_edit)
        self.ollama_url_edit = QLineEdit(describe_group)
        self.ollama_url_edit.setObjectName("ollamaUrlEdit")
        self.ollama_url_edit.setText(self.settings.get("ollama_url"))
        self.ollama_url_edit.editingFinished.connect(
            self._on_settings_changed)
        describe_form.addRow("Ollama address", self.ollama_url_edit)
        right_layout.addWidget(describe_group)

        describe_row = QHBoxLayout()
        self.describe_button = QPushButton("Describe", right)
        self.describe_button.setObjectName("describeButton")
        self.describe_button.clicked.connect(self._on_describe)
        describe_row.addWidget(self.describe_button)
        self.cancel_button = QPushButton("Cancel", right)
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel_describe)
        describe_row.addWidget(self.cancel_button)
        right_layout.addLayout(describe_row)

        self.description_text = QTextEdit(right)
        self.description_text.setObjectName("descriptionText")
        self.description_text.setReadOnly(True)
        self.description_text.setPlaceholderText(
            "The description appears here.")
        # Fixed height: a QTextEdit's size hint is ~190 px tall, which
        # pushed the whole right pane past the window. Long
        # descriptions scroll inside the box.
        self.description_text.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.description_text.setFixedHeight(68)
        right_layout.addWidget(self.description_text)
        self.measurements_label = QLabel("", right)
        self.measurements_label.setObjectName("measurementsLabel")
        self.measurements_label.setWordWrap(True)
        # Minimum two lines: a cache hit appends "  (from cache)" and
        # the text wraps, but the layout never re-grows a word-wrapped
        # label after setText (probed: height stayed 17 px while the
        # size hint said 34), so the second line rendered half-cut.
        self.measurements_label.setMinimumHeight(
            2 * self.measurements_label.fontMetrics().lineSpacing())
        right_layout.addWidget(self.measurements_label)

        cache_row = QHBoxLayout()
        self.cache_label = QLabel("", right)
        self.cache_label.setObjectName("cacheLabel")
        cache_row.addWidget(self.cache_label, 1)
        self.clear_cache_button = QPushButton("Clear cache", right)
        self.clear_cache_button.setObjectName("clearCacheButton")
        self.clear_cache_button.clicked.connect(self._on_clear_cache)
        cache_row.addWidget(self.clear_cache_button)
        right_layout.addLayout(cache_row)
        right_layout.addStretch(1)

        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([520, 560])
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
        self._on_settings_changed()

    def _build_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        add_action = QAction("Add images", self)
        add_action.setShortcut(QKeySequence.Open)
        add_action.triggered.connect(self._on_add_images)
        file_menu.addAction(add_action)
        optimize_action = QAction("Optimize all", self)
        optimize_action.triggered.connect(self._on_optimize_all)
        file_menu.addAction(optimize_action)
        cache_action = QAction("Clear cache", self)
        cache_action.triggered.connect(self._on_clear_cache)
        file_menu.addAction(cache_action)
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
        about_action = QAction("About Vision Image Optimizer", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # -- geometry -----------------------------------------------------
    def _restore_geometry(self):
        saved = self.settings.get_geometry()
        if saved:
            self.restoreGeometry(QByteArray(saved))
        else:
            self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def closeEvent(self, event):
        # Closing mid-run stops the subprocess: cancel kills it, and
        # wait() reaps the thread before the window goes away.
        for worker in (self._worker, self._stats_worker,
                       self._clear_worker):
            if worker is not None:
                worker.cancel()
                worker.wait(3000)
        self.settings.set_geometry(bytes(self.saveGeometry()))
        super().closeEvent(event)

    # -- image list ---------------------------------------------------
    def add_images(self, paths):
        """Add image files. Returns (added, failures).

        Dimensions come from QPixmap and the file size from the
        filesystem, never PIL in the GUI.
        """
        added = 0
        failures = []
        for path in paths:
            if not os.path.isfile(path):
                failures.append((path, "not a file"))
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                failures.append((path, "not a supported picture"))
                continue
            pixmap = QPixmap(path)
            if pixmap.isNull():
                failures.append((path, "could not read the picture"))
                continue
            record = {
                "path": os.path.abspath(path),
                "name": os.path.basename(path),
                "width": pixmap.width(),
                "height": pixmap.height(),
                "bytes": os.path.getsize(path),
                "crop": None,
                "description": "",
                "measurements": None,
                "optimized_path": "",
            }
            self.images.append(record)
            self.image_list.addItem(QListWidgetItem(""))
            added += 1
            self.logger.action("added image %s" % record["name"])
        self._refresh_list()
        self._update_estimates()
        self._update_buttons()
        self.empty_label.setVisible(not self.images)
        if failures:
            lines = ["Could not read these files:"]
            for path, reason in failures:
                lines.append("%s: %s"
                             % (os.path.basename(path), reason))
                self.logger.warning("could not read %s: %s",
                                    path, reason)
            QMessageBox.information(self, "Some files could not "
                                    "be read", "\n".join(lines))
        return added, failures

    def _current_record(self):
        row = self.image_list.currentRow()
        if 0 <= row < len(self.images):
            return self.images[row]
        return None

    def _estimate_for(self, record):
        """(tokens before, tokens after, after width, after height)."""
        crop = record["crop"]
        if crop is not None:
            w, h = crop[2], crop[3]
        else:
            w, h = record["width"], record["height"]
        before = vision_tokens(record["width"], record["height"])
        new_w, new_h = target_size(w, h, self.settings.target_width())
        return before, vision_tokens(new_w, new_h), new_w, new_h

    def _refresh_list(self):
        for row, record in enumerate(self.images):
            before, after, _, _ = self._estimate_for(record)
            item = self.image_list.item(row)
            item.setText("%s  %d to %d tokens"
                         % (record["name"], before, after))

    def _on_selection_changed(self, row):
        record = self._current_record()
        if record is None:
            self.preview.clear_image()
            self.description_text.setPlainText("")
            self.measurements_label.setText("")
            self._set_crop_boxes(None, None)
        else:
            pixmap = QPixmap(record["path"])
            if pixmap.isNull():
                self.preview.clear_image()
                self.status_bar.showMessage(
                    "Could not show %s" % record["name"])
            else:
                self.preview.set_image(pixmap, record["width"],
                                       record["height"])
                self.preview.set_crop(record["crop"])
            self.description_text.setPlainText(
                record["description"])
            if record["measurements"]:
                self.measurements_label.setText(
                    format_measurements(record["measurements"]))
            else:
                self.measurements_label.setText("")
            self._set_crop_boxes(record, record["crop"])
        self._update_estimates()
        self._update_buttons()

    # -- crop ---------------------------------------------------------
    def _set_crop_boxes(self, record, box):
        self._syncing_crop = True
        if record is None:
            self.crop_x.setValue(0)
            self.crop_y.setValue(0)
            self.crop_w.setValue(1)
            self.crop_h.setValue(1)
        elif box is None:
            self.crop_x.setValue(0)
            self.crop_y.setValue(0)
            self.crop_w.setValue(record["width"])
            self.crop_h.setValue(record["height"])
        else:
            self.crop_x.setValue(box[0])
            self.crop_y.setValue(box[1])
            self.crop_w.setValue(box[2])
            self.crop_h.setValue(box[3])
        for spin in (self.crop_x, self.crop_y, self.crop_w,
                     self.crop_h):
            spin.setEnabled(record is not None)
        self.full_image_button.setEnabled(record is not None)
        self._syncing_crop = False

    def _on_crop_changed(self, box):
        record = self._current_record()
        if record is None:
            return
        record["crop"] = box
        self._set_crop_boxes(record, box)
        self._refresh_list()
        self._update_estimates()

    def _on_crop_spin_changed(self):
        if self._syncing_crop:
            return
        record = self._current_record()
        if record is None:
            return
        box = (self.crop_x.value(), self.crop_y.value(),
               self.crop_w.value(), self.crop_h.value())
        clamped = clamp_crop(box, record["width"],
                             record["height"])
        if clamped == (0, 0, record["width"], record["height"]):
            record["crop"] = None
            self.preview.set_crop(None)
        else:
            record["crop"] = clamped
            self.preview.set_crop(clamped)
        self._refresh_list()
        self._update_estimates()

    def _on_full_image(self):
        record = self._current_record()
        if record is None:
            return
        record["crop"] = None
        self.preview.set_crop(None)
        self._set_crop_boxes(record, None)
        self._refresh_list()
        self._update_estimates()

    # -- settings -----------------------------------------------------
    def _on_settings_changed(self):
        self.settings.set("size_preset",
                          self.size_preset.currentText())
        self.settings.set("custom_width", self.custom_width.value())
        self.settings.set("quality_preset",
                          self.quality_preset.currentText())
        self.settings.set("custom_quality",
                          self.custom_quality.value())
        self.settings.set("output_format",
                          self.format_combo.currentText())
        self.settings.set("output_folder",
                          self.output_folder.text().strip())
        self.settings.set("prompt", self.prompt_edit.text())
        self.settings.set("fast_model",
                          self.fast_model_edit.text().strip())
        self.settings.set("smart_model",
                          self.smart_model_edit.text().strip())
        self.settings.set("ollama_url",
                          self.ollama_url_edit.text().strip())
        self.custom_width.setEnabled(
            self.size_preset.currentText() == "Custom")
        self.custom_quality.setEnabled(
            self.quality_preset.currentText() == "Custom")
        self._settings_form.setRowVisible(
            self._custom_width_row,
            self.size_preset.currentText() == "Custom")
        self._settings_form.setRowVisible(
            self._custom_quality_row,
            self.quality_preset.currentText() == "Custom")
        self._refresh_list()
        self._update_estimates()

    # -- subprocess arguments -----------------------------------------
    def _shrink_args(self, record):
        """CLI args for `python -m optimizer.shrink` for this record.

        Every value is passed explicitly: the subprocess reads its
        own settings store, which in tests is not the window's.
        """
        args = [record["path"], "--json"]
        width = self.settings.target_width()
        if width is None:
            args.append("--original-width")
        else:
            args += ["--width", str(width)]
        args += ["--quality", str(self.settings.quality())]
        args += ["--format", self.settings.get("output_format")]
        out_dir = self.settings.get("output_folder") or ""
        if out_dir:
            args += ["--out-dir", out_dir]
        if record["crop"] is not None:
            args += ["--crop", "%d,%d,%d,%d" % record["crop"]]
        if not self.settings.get("cache_enabled"):
            args.append("--no-cache")
        return args

    def _describe_args(self):
        """Option flags for `python -m optimizer.describe` (the file
        path goes first, once the shrink step has produced it)."""
        args = ["--prompt", self.settings.get("prompt"),
                "--fast-model", self.settings.get("fast_model"),
                "--smart-model", self.settings.get("smart_model"),
                "--ollama-url", self.settings.get("ollama_url"),
                "--json"]
        if not self.settings.get("cache_enabled"):
            args.append("--no-cache")
        return args

    def _update_estimates(self):
        record = self._current_record()
        total_before = 0
        total_after = 0
        for item in self.images:
            before, after, _, _ = self._estimate_for(item)
            total_before += before
            total_after += after
        if record is None:
            if self.images:
                self.token_label.setText("Select an image to see "
                                         "its tokens")
            else:
                self.token_label.setText("No image selected")
        else:
            before, after, _, _ = self._estimate_for(record)
            if after > 0 and before > after:
                ratio = before / after
                self.token_label.setText(
                    "Vision tokens: %d to %d (about %dx less "
                    "vision work)" % (before, after, round(ratio)))
            else:
                self.token_label.setText(
                    "Vision tokens: %d to %d" % (before, after))
        if self.images:
            self.totals_label.setText(
                "All images: %d tokens to %d tokens"
                % (total_before, total_after))
        else:
            self.totals_label.setText("")

    def _update_buttons(self):
        has_images = bool(self.images)
        has_selection = self._current_record() is not None
        # Work is in flight from the moment the worker exists until
        # its done/failed/cancelled slot clears it; checking
        # isRunning() here races thread startup and leaves Cancel
        # disabled.
        busy = self._worker is not None
        self.optimize_button.setEnabled(has_selection and not busy)
        self.optimize_all_button.setEnabled(has_images and not busy)
        self.describe_button.setEnabled(has_selection and not busy)
        self.cancel_button.setEnabled(busy)

    def _set_busy(self, busy, message=None):
        self.busy_light.setProperty("busy", busy)
        self.busy_light.style().unpolish(self.busy_light)
        self.busy_light.style().polish(self.busy_light)
        if message is not None:
            self.status_bar.showMessage(message)
        self._update_buttons()

    def _start_worker(self, worker):
        self._worker = worker
        worker.done.connect(worker.deleteLater)
        if hasattr(worker, "failed"):
            worker.failed.connect(worker.deleteLater)
        if hasattr(worker, "cancelled"):
            worker.cancelled.connect(worker.deleteLater)

    # -- optimize -----------------------------------------------------
    def _on_optimize_selected(self):
        record = self._current_record()
        if record is not None and self._worker is None:
            self._start_optimize([record])

    def _on_optimize_all(self):
        if self.images and self._worker is None:
            self._start_optimize(list(self.images))

    def _start_optimize(self, records):
        jobs = [(record, self._shrink_args(record))
                for record in records]
        worker = OptimizeWorker(jobs, self)
        worker.done.connect(self._on_optimize_finished)
        worker.cancelled.connect(self._on_optimize_cancelled)
        self._start_worker(worker)
        self._set_busy(True, "Optimizing...")
        worker.start()

    def _on_optimize_finished(self, results):
        self._worker = None
        self._set_busy(False, "Ready")
        saved = []
        for record, payload, error in results:
            if error is not None:
                self.logger.error("optimize failed for %s: %s",
                                  record["path"], error)
                self.status_bar.showMessage(
                    "Could not optimize %s" % record["name"])
                continue
            record["optimized_path"] = payload["path"]
            saved.append(payload["path"])
            self.logger.action(
                "optimized %s: %d to %d tokens, %s to %s"
                % (record["name"], payload["tokens_before"],
                   payload["tokens_after"],
                   human_size(payload["bytes_before"]),
                   human_size(payload["bytes_after"])))
        if saved:
            folder = os.path.dirname(saved[0])
            self.status_bar.showMessage(
                "Saved %d optimized picture(s) to %s"
                % (len(saved), folder))
        # Optimizing fills the cache, so the label is stale now.
        self._refresh_cache_label()

    def _on_optimize_cancelled(self):
        self._worker = None
        self._set_busy(False, "Optimize cancelled")
        self.logger.action("optimize cancelled")
        self._refresh_cache_label()

    # -- describe -----------------------------------------------------
    def _on_describe(self):
        record = self._current_record()
        if record is None or self._worker is not None:
            return
        self.logger.action("describe started for %s"
                           % record["name"])
        worker = DescribeWorker(self._shrink_args(record),
                                self._describe_args(), self)
        worker.done.connect(self._on_describe_finished)
        worker.failed.connect(self._on_describe_failed)
        worker.cancelled.connect(self._on_describe_cancelled)
        self._start_worker(worker)
        self.description_text.setPlainText("")
        self.measurements_label.setText("")
        self._set_busy(True, "Describing %s..." % record["name"])
        worker.start()

    def _on_describe_finished(self, payload):
        record = self._current_record()
        self._worker = None
        self._set_busy(False, "Ready")
        if record is None:
            return
        shrink = payload["shrink"]
        desc = payload["describe"]
        record["description"] = desc["text"]
        record["optimized_path"] = shrink["path"]
        # Tokens and sizes span the whole chain (original to
        # shrunken); the look times come from the describe step.
        measure = describe_measurements(
            desc.get("fast_seconds"), desc.get("smart_seconds"),
            shrink["tokens_before"], shrink["tokens_after"],
            shrink["bytes_before"], shrink["bytes_after"])
        record["measurements"] = measure
        self.description_text.setPlainText(desc["text"])
        measure_text = "Model: %s  %s" % (
            desc["model_used"], format_measurements(measure))
        if desc.get("from_cache"):
            measure_text += "  (from cache)"
        self.measurements_label.setText(measure_text)
        self.logger.info(
            "describe done for %s with %s%s: %s"
            % (record["name"], desc["model_used"],
               " (from cache)" if desc.get("from_cache") else "",
               measure_text))
        self._refresh_cache_label()

    def _on_describe_failed(self, message):
        self._worker = None
        self._set_busy(False, "Ready")
        self.description_text.setPlainText(message)
        self.logger.warning("describe failed: %s", message)

    def _on_describe_cancelled(self):
        self._worker = None
        self._set_busy(False, "Describe cancelled")
        self.logger.action("describe cancelled")

    def _on_cancel_describe(self):
        # cancel() is safe before the thread starts: run() checks
        # the flag first and reports cancelled.
        if self._worker is not None:
            self._worker.cancel()
            self.status_bar.showMessage("Cancelling...")

    # -- cache, report, menus -----------------------------------------
    def _refresh_cache_label(self):
        if self._stats_worker is not None:
            self._stats_pending = True
            return
        worker = CliWorker(["cache-stats", "--json"], True, self)
        worker.done.connect(self._on_cache_stats)
        worker.done.connect(worker.deleteLater)
        self._stats_worker = worker
        worker.start()

    def _on_cache_stats(self, payload):
        self._stats_worker = None
        if payload is not None:
            self.cache_label.setText(
                "Cache: %d optimized picture(s), %d description(s), %s"
                % (payload["optimized"], payload["descriptions"],
                   human_size(payload["bytes"])))
        else:
            self.cache_label.setText("Cache: unavailable")
        if self._stats_pending:
            self._stats_pending = False
            self._refresh_cache_label()

    def _on_clear_cache(self):
        answer = QMessageBox.question(
            self, "Clear cache",
            "Clear the saved optimized pictures and descriptions? "
            "They will be made again next time.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        if self._clear_worker is not None:
            return
        worker = CliWorker(["cache-clear"], False, self)
        worker.done.connect(self._on_cache_cleared)
        worker.done.connect(worker.deleteLater)
        self._clear_worker = worker
        self.status_bar.showMessage("Clearing the cache...")
        worker.start()

    def _on_cache_cleared(self, text):
        self._clear_worker = None
        self._refresh_cache_label()
        if text:
            # The CLI prints "Cache cleared: N files removed, X
            # freed."; keep the count in the status line.
            match = re.search(r"(\d+) files? removed, (.+?) freed",
                              text)
            if match:
                self.status_bar.showMessage(
                    "Cache cleared: %s file(s) removed"
                    % match.group(1))
                self.logger.action(
                    "cache cleared (%s files, %s freed)"
                    % (match.group(1), match.group(2)))
                return
        self.status_bar.showMessage("Cache cleared")
        self.logger.action("cache cleared")

    def _on_debug_report(self):
        path = self.logger.generate_report()
        self.status_bar.showMessage("Debug report written to %s"
                                    % path)
        QMessageBox.information(
            self, "Debug report",
            "Debug report written to:\n%s\n\nSend it to "
            "broke.n.bored.studio@gmail.com if something is broken."
            % path)

    def _on_add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add images", "",
            "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.webp "
            "*.tif *.tiff)")
        if paths:
            self.add_images(paths)

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where optimized copies go")
        if folder:
            self.output_folder.setText(folder)
            self._on_settings_changed()

    def _on_how_to_use(self):
        if self._how_to_use is None:
            self._how_to_use = HowToUseWindow(self)
        self._how_to_use.show()
        self._how_to_use.raise_()
        self._how_to_use.activateWindow()

    def _on_about(self):
        QMessageBox.about(
            self, "About Vision Image Optimizer",
            "Vision Image Optimizer %s\n\nShrink pictures before a "
            "local vision model looks at them, so each look costs "
            "fewer vision tokens and less time.\n\n%s"
            % (__version__, CAVEAT_TEXT))

    # -- drag and drop ------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = [u.toLocalFile() for u in event.mimeData().urls()]
            if any(os.path.splitext(u)[1].lower()
                   in SUPPORTED_EXTENSIONS for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        images = [p for p in paths
                  if os.path.splitext(p)[1].lower()
                  in SUPPORTED_EXTENSIONS]
        if images:
            self.add_images(images)
        event.acceptProposedAction()


def run_gui():
    """Open the window. Returns the app exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("BrokeNBored")
    app.setStyleSheet(DARK_STYLESHEET)
    lock = try_single_instance()
    if lock is None:
        print("Vision Image Optimizer is already running.",
              file=sys.stderr)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
