"""Build a self-contained, windowed Windows executable with PyInstaller."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import sys

from PyInstaller.__main__ import run as run_pyinstaller
from PIL import Image
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parent
SVG_PATH = ROOT / "assets" / "vectorBridge_icon.svg"
ICON_PATH = ROOT / "assets" / "vectorBridge_icon.ico"


def _create_windows_icon(destination: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise ValueError(f"Unable to render SVG application icon: {SVG_PATH}")

    image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    png = QByteArray()
    buffer = QBuffer(png)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Unable to create PNG data for the Windows icon.")
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Unable to render SVG to PNG for the Windows icon.")
    buffer.close()

    with Image.open(BytesIO(bytes(png))) as rendered:
        rendered.save(
            destination,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    app.quit()


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("This build script creates a Windows executable and must run on Windows.")
    if not SVG_PATH.is_file():
        raise FileNotFoundError(f"Application SVG icon not found: {SVG_PATH}")

    _create_windows_icon(ICON_PATH)
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "VectorBridgeCADStudio",
            "--icon",
            str(ICON_PATH),
            "--add-data",
            f"{SVG_PATH};assets",
            "--collect-all",
            "fitz",
            "--collect-all",
            "ezdxf",
            str(ROOT / "main.py"),
        ]
    )

    executable = ROOT / "dist" / "VectorBridgeCADStudio.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller did not create the expected executable: {executable}")
    print(f"Created {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
