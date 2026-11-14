"""Hold the single-instance lock for the two-process GUI test.

Usage: python single_instance_driver.py <ready-file>

Takes the lock through ocrreader.gui.try_single_instance, writes
LOCKED to the ready file once held, then sleeps until killed.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from ocrreader import gui  # noqa: E402


def main():
    app = QCoreApplication(sys.argv)
    lock = gui.try_single_instance()
    if lock is None:
        print("driver: lock already held", file=sys.stderr)
        return 1
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        fh.write("LOCKED")
    while True:
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
