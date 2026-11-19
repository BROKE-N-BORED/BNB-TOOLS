"""Render appimage.svg to the appimage-*.png files.

Run with the venv python (which has PySide6):
  .venv/bin/python render_icons.py [output-dir]

assets/appimage.svg is the checked-in master. The PNGs are
gitignored build products: they are rendered into a temp
directory and packed into the release zip only (never into the
source tree), and the installer renders them again for the menu
icon. render_icons is intentionally small and standalone: it
does not import the appimagehelper package.
"""

import os
import sys

ICON_SIZES = (16, 32, 48, 64, 128, 256)
DEFAULT_ICON_SIZE = 128


def render(svg_path, out_dir):
    """Render one PNG per size plus the default appimage.png.
    Returns the list of written paths."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    os.makedirs(out_dir, exist_ok=True)
    renderer = QSvgRenderer(svg_path)
    written = []
    for size in ICON_SIZES:
        target = os.path.join(out_dir, "appimage-%d.png" % size)
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(target, "PNG"):
            raise RuntimeError("could not write %s" % target)
        written.append(target)
    default = os.path.join(out_dir, "appimage.png")
    image = QImage(DEFAULT_ICON_SIZE, DEFAULT_ICON_SIZE,
                   QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(default, "PNG"):
        raise RuntimeError("could not write %s" % default)
    written.append(default)
    return written


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    svg = os.path.join(here, "assets", "appimage.svg")
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        here, "assets")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])
    for path in render(svg, out_dir):
        print("wrote %s" % path)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
