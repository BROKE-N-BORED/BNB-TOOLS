"""Drive the real Song Key BPM window offscreen with real button
clicks and save screenshots for the eyeball check.

This is a script, not a test: the coordinator runs it and looks
at the pictures. It runs the REAL analyze subprocess over
generated fixtures (no stub), so it needs the forge test venv:

  ~/workspace/forge-v2-testenv/bin/python tests/proof_drive.py

Screenshots land in --out-dir (default /tmp/songkey-proof):
empty state, filled table, How to Use. Nothing is written into
the tree: screenshots are binaries and the tree stays text.
"""

import argparse
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp")

_QT_LIB = os.path.expanduser(
    "~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu")
if os.path.isdir(_QT_LIB):
    _old_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _QT_LIB not in _old_ld.split(os.pathsep):
        os.environ["LD_LIBRARY_PATH"] = (
            _QT_LIB + os.pathsep + _old_ld if _old_ld else _QT_LIB)
    os.environ.setdefault(
        "__EGL_VENDOR_LIBRARY_DIRS",
        os.path.expanduser("~/workspace/qt-libs/root/usr/share"
                           "/glvnd/egl_vendor.d"))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from songkey import gui  # noqa: E402
from songkey.debug_log import DebugLogger  # noqa: E402
from songkey.settings import Settings  # noqa: E402


def wait_until(app, predicate, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def shoot(widget, path):
    """Grab a screenshot; fail loudly when the save fails
    (grab().save() returns False and writes nothing)."""
    ok = widget.grab().save(path)
    if not ok or not os.path.exists(path):
        raise SystemExit("screenshot failed: %s" % path)
    print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))


def main():
    parser = argparse.ArgumentParser(
        description="Drive the Song Key BPM window and save "
                    "screenshots.")
    parser.add_argument("--out-dir", default="/tmp/songkey-proof",
                        help="screenshot folder "
                             "(default: /tmp/songkey-proof)")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    tmp = tempfile.TemporaryDirectory()
    # Keep the proof run out of the real home: the lock file and
    # the last-folder setting both live under XDG_DATA_HOME.
    os.environ["XDG_DATA_HOME"] = os.path.join(tmp.name, "data")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp.name, "config")

    app = QApplication([])
    app.setStyleSheet(gui.DARK_STYLESHEET)
    logger = DebugLogger("song-key-bpm", "0.1.0",
                         log_dir=os.path.join(tmp.name, "logs"))
    settings = Settings(
        path=os.path.join(tmp.name, "settings.json"))
    window = gui.MainWindow(settings=settings, logger=logger)
    window.show()
    app.processEvents()

    # 1. Empty state: no files loaded.
    shoot(window, os.path.join(args.out_dir, "01-empty.png"))

    # 2. Filled table: real Analyze button, real analyze run.
    click = helpers.make_fixture("click120", tmp.name)
    aminor = helpers.make_fixture("aminor", tmp.name)
    combo = helpers.make_fixture("combo", tmp.name)
    window.add_files([click, aminor, combo])
    app.processEvents()
    window.analyze_button.click()
    if not wait_until(app, lambda: window._worker is None):
        raise SystemExit("analyze run did not finish")
    app.processEvents()
    print("table rows: %d" % window.results_table.rowCount())
    for row in range(window.results_table.rowCount()):
        cells = [window.results_table.item(row, col).text()
                 for col in range(5)]
        print("  " + " | ".join(cells))
    shoot(window, os.path.join(args.out_dir, "02-filled.png"))

    # 3. How to Use window.
    window._on_how_to_use()
    app.processEvents()
    shoot(window._how_to_use,
          os.path.join(args.out_dir, "03-how-to-use.png"))

    window.close()
    logger.uninstall_crash_handler()
    print("done: %s" % args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
