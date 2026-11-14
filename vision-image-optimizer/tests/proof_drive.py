#!/usr/bin/env python3
"""GUI proof for Vision Image Optimizer v0.2.0 (S63 harness).

Opens the REAL thin-viewer window from a fresh unzip under Xvfb,
drives it end to end (add image, set 512w, optimize via the shrink
subprocess, describe via shrink + describe subprocesses against the
fake Ollama server, cancel path, cache hit on second describe), and
saves screenshots for eyeballing.

Run separately from the suite, from the fresh unzip:

    xvfb-run -a python -u tests/proof_drive.py \
        --shots ~/workspace/vision-optimizer-verify-v020/shots \
        --log ~/workspace/vision-optimizer-verify-v020/proof.log

S63 rules followed: persistent QTimer safety watcher from the
start, python -u, log to a file, absolute paths, wall-clock waits,
the app's real stylesheet applied in the harness, stderr checked
for RecursionError / SystemError / tracebacks after the run.

The window is pointed at the fake server through the ollama_url
setting (there is no injected client any more), and the fake
server's cache is isolated by pointing XDG_CACHE_HOME and
XDG_CONFIG_HOME at the state folder before anything runs.
"""

import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.dirname(HERE)
sys.path.insert(0, TREE)
sys.path.insert(0, HERE)

from helpers import GOOD_DESCRIPTION, FakeOllama, make_image  # noqa: E402
from optimizer import __version__, gui  # noqa: E402
from optimizer.debug_log import DebugLogger  # noqa: E402
from optimizer.settings import Settings  # noqa: E402
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QMessageBox)

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" :: " + detail) if detail else ""),
          flush=True)
    return ok


def wait_until(predicate, timeout, app, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(step)
    app.processEvents()
    return predicate()


def screenshot(window, path):
    pixmap = window.grab()
    ok = pixmap.save(path)
    # grab().save() fails silently — the file must exist.
    if not ok or not os.path.exists(path):
        raise RuntimeError("screenshot failed: %s" % path)
    print("shot: %s (%d bytes)"
          % (path, os.path.getsize(path)), flush=True)


class SafetyWatcher:
    """Persistent modal watcher: records unexpected dialogs and
    dismisses them, so a surprise modal can never trap a pump."""

    def __init__(self, app, log):
        self.app = app
        self.log = log
        self.seen = []
        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _poll(self):
        for widget in self.app.topLevelWidgets():
            if not isinstance(widget, QDialog):
                continue
            if not widget.isVisible() or not widget.isModal():
                continue
            if widget in self.seen:
                continue
            self.seen.append(widget)
            title = widget.windowTitle()
            text = ""
            if isinstance(widget, QMessageBox):
                text = widget.text()
            entry = "unexpected modal: %r %r" % (title, text)
            print(entry, flush=True)
            self.log.write(entry + "\n")
            self.log.flush()
            button = None
            if isinstance(widget, QMessageBox):
                button = widget.defaultButton()
            if button is not None:
                button.click()
            else:
                widget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", required=True,
                        help="screenshot folder (absolute path)")
    parser.add_argument("--log", required=True,
                        help="log file (absolute path)")
    parser.add_argument("--state", default=None,
                        help="state folder (default: <shots>/../state)")
    args = parser.parse_args()
    shots = os.path.abspath(args.shots)
    state = os.path.abspath(
        args.state or os.path.join(os.path.dirname(shots), "state"))
    os.makedirs(shots, exist_ok=True)
    os.makedirs(state, exist_ok=True)

    # Isolate the subprocesses' settings + cache stores (they read
    # their own stores, not the window's): set before anything runs.
    os.environ["XDG_CACHE_HOME"] = os.path.join(state, "xdg-cache")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(state, "xdg-config")

    log = open(os.path.abspath(args.log), "w", encoding="utf-8")
    log.write("proof run from tree: %s\n" % TREE)
    log.write("version: %s\n" % __version__)
    log.flush()

    # The QApplication comes first, before any image work.
    app = QApplication(sys.argv)
    app.setStyleSheet(gui.DARK_STYLESHEET)
    watcher = SafetyWatcher(app, log)

    servers = []
    try:
        # Persistent test assets in the workspace, never /tmp.
        img1 = os.path.join(state, "shot-1080p.png")
        img2 = os.path.join(state, "shot-small.png")
        make_image(img1, 1920, 1080)
        make_image(img2, 800, 600)

        qsettings = QSettings(os.path.join(state, "settings.ini"),
                              QSettings.IniFormat)
        settings = Settings(qsettings)
        logger = DebugLogger("vision-image-optimizer", __version__,
                             log_dir=os.path.join(state, "logs"))

        server = FakeOllama().start()
        servers.append(server)
        settings.set("ollama_url", server.base_url)

        window = gui.MainWindow(settings=settings, logger=logger)
        window.show()
        app.processEvents()
        check("window opens at default size",
              window.size().width() == 1100
              and window.size().height() == 650,
              "%dx%d" % (window.size().width(),
                         window.size().height()))
        check("empty state visible",
              window.empty_label.isVisible()
              and "Drop images here" in window.preview.text())
        check("nothing selected by default",
              window.image_list.currentRow() == -1)
        screenshot(window, os.path.join(shots, "01-empty.png"))

        # Add images, select the 1080p one.
        window.add_images([img1, img2])
        window.image_list.setCurrentRow(0)
        app.processEvents()
        check("two images listed",
              window.image_list.count() == 2)
        check("token estimate 2040 to 144",
              "2040" in window.token_label.text()
              and "144" in window.token_label.text(),
              window.token_label.text())
        check("totals line present",
              "tokens to" in window.totals_label.text(),
              window.totals_label.text())
        check("caveat visible",
              "does not get 14x faster"
              in window.caveat_label.text())
        screenshot(window, os.path.join(shots, "02-image-added.png"))

        # 512w is the default; set it explicitly and optimize
        # (async now: the shrink subprocess runs in a thread).
        window.size_preset.setCurrentText("512w")
        app.processEvents()
        window.optimize_button.click()
        out = os.path.join(state, "optimized", "shot-1080p-512w.jpg")
        ok = wait_until(lambda: os.path.exists(out), 15, app)
        check("optimize wrote the file", ok, out)
        if os.path.exists(out):
            from PIL import Image
            with Image.open(out) as shot:
                check("optimized picture is 512x288",
                      shot.size == (512, 288), str(shot.size))
        ok = wait_until(lambda: window._worker is None, 10, app)
        check("optimize worker finishes", ok)
        check("cache label shows the optimized picture",
              wait_until(lambda: "1 optimized picture(s)" in
                         window.cache_label.text(), 15, app),
              window.cache_label.text())
        screenshot(window, os.path.join(shots, "03-optimized.png"))

        # Describe against the fake server (shrink subprocess,
        # then describe subprocess on the shrunken copy).
        started = time.monotonic()
        window.describe_button.click()
        app.processEvents()
        check("busy light on while describing",
              window.busy_light.property("busy") is True)
        ok = wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), 20, app)
        elapsed = time.monotonic() - started
        check("describe fills the description", ok)
        check("measurements line has tokens and model",
              "Tokens: 2040 to 144" in
              window.measurements_label.text()
              and "minicpm-v" in window.measurements_label.text(),
              window.measurements_label.text())
        print("describe wall time: %.2f s" % elapsed, flush=True)
        log.write("describe wall time: %.2f s\n" % elapsed)
        check("busy light off after describing",
              window.busy_light.property("busy") is False)
        screenshot(window, os.path.join(shots, "04-described.png"))

        # Second describe: cache hit, no new server call.
        calls_before = len(server.calls)
        window.description_text.setPlainText("")
        window.describe_button.click()
        ok = wait_until(
            lambda: GOOD_DESCRIPTION in
            window.description_text.toPlainText(), 20, app)
        check("second describe fills the description", ok)
        check("cache hit visibly marked",
              "from cache" in window.measurements_label.text(),
              window.measurements_label.text())
        check("no new server call on cache hit",
              len(server.calls) == calls_before,
              "%d calls" % len(server.calls))
        screenshot(window, os.path.join(shots, "05-cache-hit.png"))

        # Cancel path: slow server + a fresh prompt (busts the
        # description cache), cancel mid-call, nothing lands.
        # The window is repointed through the Ollama address box,
        # the way a user would do it.
        slow = FakeOllama(delay=3.0).start()
        servers.append(slow)
        window.ollama_url_edit.setText(slow.base_url)
        window.ollama_url_edit.editingFinished.emit()
        window.prompt_edit.setText(
            "Describe this image in plain words, second look.")
        window.prompt_edit.editingFinished.emit()
        window.description_text.setPlainText("")
        window.describe_button.click()
        ok = wait_until(
            lambda: window.cancel_button.isEnabled(), 5, app)
        check("cancel button enables while describing", ok)
        # Let the shrink step finish so the cancel lands mid-describe.
        time.sleep(1.0)
        app.processEvents()
        window.cancel_button.click()
        ok = wait_until(lambda: window._worker is None, 10, app)
        check("worker stops after cancel", ok)
        check("cancelled describe leaves no description",
              window.description_text.toPlainText() == "")
        screenshot(window, os.path.join(shots, "06-cancelled.png"))
        window.ollama_url_edit.setText(server.base_url)
        window.ollama_url_edit.editingFinished.emit()

        # Crop: rubber-band drag on the preview.
        preview = window.preview
        rect = preview._display_rect_for()
        start = rect.topLeft() + QPoint(10, 10)
        end = rect.center()
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(preview, pos=end)
        QTest.mouseRelease(preview, Qt.LeftButton, pos=end)
        app.processEvents()
        crop = preview.crop()
        check("rubber band sets a crop", crop is not None,
              str(crop))
        if crop is not None:
            check("crop spin boxes match the band",
                  window.crop_w.value() == crop[2]
                  and window.crop_h.value() == crop[3])
        screenshot(window, os.path.join(shots, "07-crop.png"))
        window.full_image_button.click()
        app.processEvents()
        check("Full image clears the crop",
              preview.crop() is None)

        # How to Use window.
        window._on_how_to_use()
        app.processEvents()
        check("How to Use window opens",
              window._how_to_use is not None
              and window._how_to_use.isVisible())
        screenshot(window._how_to_use,
                   os.path.join(shots, "08-how-to-use.png"))
        window._how_to_use.close()

        check("no unexpected modals appeared",
              len(watcher.seen) == 0,
              "%d seen" % len(watcher.seen))

        window.close()
        app.processEvents()
    except Exception:
        log.write(traceback.format_exc())
        log.flush()
        print(traceback.format_exc(), flush=True)
        return 1
    finally:
        for server in servers:
            server.stop()
        log.close()

    failed = [c for c in CHECKS if not c[1]]
    print("proof: %d checks, %d passed, %d failed"
          % (len(CHECKS), len(CHECKS) - len(failed), len(failed)),
          flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
