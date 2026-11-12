"""Drag-and-drop batch queue table."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


class QueueWidget(QTableWidget):
    """Table accepting PDF drops and tracking per-file conversion progress."""

    files_dropped = pyqtSignal(list)
    HEADERS = ("File Name", "Path", "Status", "Output Format", "Progress")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setStretchLastSection(True)
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event: object) -> None:
        mime = event.mimeData()  # type: ignore[attr-defined]
        if mime.hasUrls() and any(url.toLocalFile().lower().endswith(".pdf") for url in mime.urls()):
            event.acceptProposedAction()  # type: ignore[attr-defined]
        else:
            event.ignore()  # type: ignore[attr-defined]

    def dragMoveEvent(self, event: object) -> None:
        event.acceptProposedAction()  # type: ignore[attr-defined]

    def dropEvent(self, event: object) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()  # type: ignore[attr-defined]
            if url.toLocalFile().lower().endswith(".pdf")
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()  # type: ignore[attr-defined]
        else:
            event.ignore()  # type: ignore[attr-defined]

    def add_files(self, paths: list[str]) -> None:
        existing = {
            self.item(row, 1).text().casefold()
            for row in range(self.rowCount())
            if self.item(row, 1) is not None
        }
        for raw_path in paths:
            path = str(Path(raw_path).resolve())
            if path.casefold() in existing:
                continue
            row = self.rowCount()
            self.insertRow(row)
            self.setItem(row, 0, QTableWidgetItem(Path(path).name))
            self.setItem(row, 1, QTableWidgetItem(path))
            self.setItem(row, 2, QTableWidgetItem("Pending"))
            format_combo = QComboBox()
            format_combo.addItems([".dxf", ".dwg"])
            self.setCellWidget(row, 3, format_combo)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(0)
            self.setCellWidget(row, 4, progress)

    def status(self, row: int, value: str) -> None:
        item = self.item(row, 2)
        if item is not None:
            item.setText(value)

    def progress(self, row: int, value: int) -> None:
        bar = self.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            bar.setValue(value)

    def output_format(self, row: int) -> str:
        combo = self.cellWidget(row, 3)
        return combo.currentText() if isinstance(combo, QComboBox) else ".dxf"
