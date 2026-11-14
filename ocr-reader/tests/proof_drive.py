"""Drive the real OCR Reader window offscreen with real button
clicks and save screenshots for the eyeball check.

This is a script, not a test: the coordinator runs it and looks
at the pictures. It drives the window against STUBBED CLI
responses (canned JSON on PATH), so it needs no real tesseract
and no Worker A files:

  ~/workspace/forge-v2-testenv/bin/python tests/proof_drive.py

Screenshots land in --out-dir (default
~/workspace/t32-verify/shots): empty state, after Read, after
Clean. Nothing is written into the tree: screenshots are
binaries and the tree stays text.
"""

import argparse
import os
import stat
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from ocrreader import gui  # noqa: E402
from ocrreader.debug_log import DebugLogger  # noqa: E402
from ocrreader.settings import Settings  # noqa: E402

STUB_READ = '''#!/usr/bin/env python3
import json, os, sys
results = []
skip_next = False
for path in sys.argv[1:]:
    if skip_next:
        skip_next = False
        continue
    if path == "--lang":
        skip_next = True
        continue
    if path.startswith("--"):
        continue
    name = os.path.basename(path)
    base = {"path": os.path.abspath(path), "file": name,
            "text": "", "pages": 1, "language": "eng",
            "error": None}
    if "note" in name:
        base["text"] = "This is a wrapped\\nline of text\\nfrom a note."
    elif "clean" in name:
        base["text"] = "Already tidy text."
    else:
        base.update(error="This file is not a readable image",
                    pages=0)
    results.append(base)
print(json.dumps(results))
'''

STUB_CLEAN = '''#!/usr/bin/env python3
import json, sys
path = [a for a in sys.argv[1:] if not a.startswith("--")][0]
with open(path, encoding="utf-8") as fh:
    text = fh.read()
lines = [ln for ln in text.splitlines() if ln.strip()]
joined = " ".join(lines)
changes = []
if len(lines) > 1:
    changes.append("joined %d wrapped lines" % len(lines))
print(json.dumps({"text": joined, "changes": changes}))
'''


def install_stub(bindir, name, source):
    path = os.path.join(bindir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(source)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR
             | stat.S_IXGRP | stat.S_IXOTH)
    return path


def wait_until(app, predicate, timeout=60.0):
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
        description="Drive the OCR Reader window and save "
                    "screenshots.")
    parser.add_argument("--out-dir",
                        default=os.path.expanduser(
                            "~/workspace/t32-verify/shots"),
                        help="screenshot folder "
                             "(default: ~/workspace/t32-verify/shots)")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    tmp = tempfile.TemporaryDirectory()
    # Keep the proof run out of the real home: the lock file and
    # the last-folder setting both live under XDG_DATA_HOME.
    os.environ["XDG_DATA_HOME"] = os.path.join(tmp.name, "data")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp.name, "config")

    # Stub CLI tools on PATH: the window runs these, not real OCR.
    bindir = os.path.join(tmp.name, "bin")
    os.makedirs(bindir, exist_ok=True)
    install_stub(bindir, "ocr-read", STUB_READ)
    install_stub(bindir, "ocr-clean", STUB_CLEAN)
    os.environ["PATH"] = bindir + os.pathsep + os.environ.get(
        "PATH", "")

    # Fake image files: the stubs key on the name and never open
    # them.
    note = os.path.join(tmp.name, "note.png")
    clean_png = os.path.join(tmp.name, "clean.png")
    for path in (note, clean_png):
        with open(path, "wb"):
            pass

    app = QApplication([])
    app.setStyleSheet(gui.DARK_STYLESHEET)
    logger = DebugLogger("ocr-reader", "0.1.0",
                         log_dir=os.path.join(tmp.name, "logs"))
    settings = Settings(
        path=os.path.join(tmp.name, "settings.json"))
    window = gui.MainWindow(settings=settings, logger=logger)
    window.show()
    app.processEvents()

    # 1. Empty state: no files loaded.
    shoot(window, os.path.join(args.out_dir, "01-empty.png"))

    # 2. After Read: real Read button, stubbed read run.
    window.add_files([note, clean_png])
    app.processEvents()
    window.read_button.click()
    if not wait_until(app, lambda: window._worker is None):
        raise SystemExit("read run did not finish")
    app.processEvents()
    print("text pane: %r" % window.text_pane.toPlainText())
    print("status: %s" % window.status_bar.currentMessage())
    shoot(window, os.path.join(args.out_dir, "02-read.png"))

    # 3. After Clean: real Clean button, stubbed clean run.
    window.clean_button.click()
    if not wait_until(app, lambda: window._worker is None):
        raise SystemExit("clean run did not finish")
    app.processEvents()
    print("cleaned pane: %r" % window.text_pane.toPlainText())
    print("status: %s" % window.status_bar.currentMessage())
    shoot(window, os.path.join(args.out_dir, "03-cleaned.png"))

    window.close()
    logger.uninstall_crash_handler()
    print("done: %s" % args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
