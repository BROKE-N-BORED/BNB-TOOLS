"""Offscreen proof drive for AppImage Runner.

Run with the Qt env (see run_tests.sh):
    python tests/proof_drive.py

Drives the real MainWindow offscreen with a stubbed
appimagehelper-cli on PATH (canned JSON), picks a file, runs
it, and saves screenshots of each state to
~/workspace/t40-verify/shots/ for a human to eyeball. The
window geometry, the plain-words status text, and the
phone-first checklist are what the screenshots prove.

Exits nonzero on the first failed expectation.
"""

import os
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from appimagehelper import gui  # noqa: E402
from appimagehelper.logsetup import make_logger  # noqa: E402
from appimagehelper.settings import Settings  # noqa: E402

SHOTS = os.path.expanduser("~/workspace/t40-verify/shots")

STUB_OK = """#!/bin/sh
cat <<'JSON'
{"command": "launch", "path": "/tmp/Fake.AppImage",
 "made_runnable": true, "already": false, "pid": 4242,
 "running": true, "finished": false, "error": null}
JSON
"""


def check(condition, message):
    if not condition:
        raise SystemExit("PROOF DRIVE FAILED: %s" % message)
    print("ok: %s" % message)


def grab(widget, name):
    path = os.path.join(SHOTS, name)
    pixmap = widget.grab()
    check(not pixmap.isNull(), "grabbed %s" % name)
    check(pixmap.save(path), "saved %s" % path)
    print("shot: %s (%dx%d)" % (path, pixmap.width(),
                                pixmap.height()))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyleSheet(gui.DARK_STYLESHEET)

    tmp = tempfile.mkdtemp(prefix="appimage-proof-")

    # Stub CLI on PATH: the window must run it, not the core.
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    stub = os.path.join(bindir, "appimagehelper-cli")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(STUB_OK)
    os.chmod(stub, stat.S_IRWXU)
    os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

    # A fake AppImage to pick (never actually run: the stub CLI
    # answers instead).
    fake = os.path.join(tmp, "AndroidFileTransfer.AppImage")
    with open(fake, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake, 0o644)

    settings = Settings(os.path.join(tmp, "settings.json"))
    logger = make_logger(log_dir_path=os.path.join(tmp, "logs"))
    qsettings = QSettings(os.path.join(tmp, "qt.ini"),
                          QSettings.IniFormat)
    window = gui.MainWindow(settings=settings, logger=logger,
                            qsettings=qsettings)
    window.show()
    app.processEvents()

    hint = window.sizeHint()
    check(window.width() >= hint.width()
          and window.height() >= hint.height(),
          "window %dx%d >= size hint %dx%d"
          % (window.width(), window.height(), hint.width(),
             hint.height()))
    check(not window.run_button.isEnabled(),
          "Run it starts disabled")
    grab(window, "01-empty.png")

    check(window.pick_file(fake), "picked the fake AppImage")
    check(window.run_button.isEnabled(),
          "Run it enabled after pick")
    app.processEvents()
    grab(window, "02-picked.png")

    window.run_button.click()
    deadline = time.time() + 10
    while time.time() < deadline and window._worker is not None:
        app.processEvents()
        time.sleep(0.02)
    check(window._worker is None, "worker finished")
    status = window.status_label.text()
    check("running now" in status,
          "status reports running: %r" % status)
    check("Made" in status,
          "status reports the bit was set: %r" % status)
    app.processEvents()
    grab(window, "03-ran.png")

    # The How to Use window, for the screenshot record.
    window._on_how_to_use()
    app.processEvents()
    check(window._how_to_use is not None
          and window._how_to_use.isVisible(),
          "How to Use window open")
    grab(window._how_to_use, "04-how-to-use.png")

    print("PROOF DRIVE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
