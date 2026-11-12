"""VectorBridge CAD Studio application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _resource_path(relative_path: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def _load_svg_icon(svg_path: Path) -> QIcon:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"Unable to load application SVG icon: {svg_path}")
    image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def main() -> int:
    """Start the application event loop."""
    app = QApplication(sys.argv)
    app.setApplicationName("VectorBridge CAD Studio")
    icon = _load_svg_icon(_resource_path("assets/vectorBridge_icon.svg"))
    app.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
