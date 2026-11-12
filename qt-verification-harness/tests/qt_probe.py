#!/usr/bin/env python3
"""Real Qt probe for T12: open a window offscreen, grab it, close it.

Run through qt_harness.py (which sets the env). Exits 0 only if the window
actually opened and the grab produced a non-empty image.
"""
import os
import sys

print("TMPDIR =", os.environ.get("TMPDIR"))
print("QT_QPA_PLATFORM =", os.environ.get("QT_QPA_PLATFORM"))
assert os.environ.get("TMPDIR") == "/tmp", "TMPDIR must be /tmp"

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

app = QApplication(sys.argv)
label = QLabel("qt-harness probe")
label.resize(320, 120)
label.show()
app.processEvents()
pix = label.grab()
print("grab: %dx%d null=%s" % (pix.width(), pix.height(), pix.isNull()))
assert not pix.isNull() and pix.width() == 320 and pix.height() == 120
QTimer.singleShot(0, app.quit)
app.exec()
print("PROBE OK: window opened, grabbed, closed")
