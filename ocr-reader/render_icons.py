#!/usr/bin/env python3
"""Render assets/ocr.svg to PNG sizes with QtSvg.

Default output is the assets/ folder (install time, fresh clone).
build_zip.py passes --out-dir so the PNGs go into the Release zip
without ever landing in the tree (snapshot pushes cannot carry
binary files).

Run in its own process, never inside a test or zip-build process:
a render crash inside the test process fails the suite instead of
the render.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SIZES = (16, 32, 48, 64, 128, 256)


def main():
    parser = argparse.ArgumentParser(
        description="Render ocr.svg to PNG icon sizes.")
    parser.add_argument("--out-dir", default=None,
                        help="output folder (default: assets/)")
    args = parser.parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else ASSETS
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PySide6.QtGui import QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QSize
    except ImportError:
        print("QtSvg not available; cannot render PNGs",
              file=sys.stderr)
        return 1

    app = QGuiApplication([])
    renderer = QSvgRenderer(str(ASSETS / "ocr.svg"))
    if not renderer.isValid():
        print("ocr.svg did not load", file=sys.stderr)
        return 1
    for size in SIZES:
        image = QImage(QSize(size, size), QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        out = out_dir / ("ocr-%d.png" % size)
        image.save(str(out))
        print("wrote %s (%d bytes)" % (out, out.stat().st_size))
    # Default icon name used by the .desktop file.
    src = out_dir / "ocr-256.png"
    dst = out_dir / "ocr.png"
    dst.write_bytes(src.read_bytes())
    print("wrote %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
