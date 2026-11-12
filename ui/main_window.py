"""Main application window and background batch conversion worker."""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.builder import ColorRule, build_dxf
from core.exporter import convert_dxf_to_dwg
from core.parser import parse_pdf
from .queue_widget import QueueWidget
from .settings_dialog import SettingsDialog


@dataclass(frozen=True)
class Job:
    row: int
    source: str
    output_format: str
    output_directory: str
    output_stem: str


class ConversionWorker(QObject):
    progress = pyqtSignal(int, int)
    overall_progress = pyqtSignal(int)
    status = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(self, jobs: list[Job], rules: list[ColorRule]) -> None:
        super().__init__()
        self.jobs, self.rules = jobs, rules
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _report_progress(self, row: int, job_index: int, value: int) -> None:
        self.progress.emit(row, value)
        total = max(1, len(self.jobs))
        self.overall_progress.emit(
            round((job_index + value / 100) * 100 / total)
        )

    @pyqtSlot()
    def run(self) -> None:
        total = len(self.jobs)
        self.overall_progress.emit(0)
        try:
            for job_index, job in enumerate(self.jobs):
                if self._cancel_event.is_set():
                    for remaining in self.jobs[job_index:]:
                        self.status.emit(remaining.row, "Cancelled")
                        self.progress.emit(remaining.row, 0)
                    break
                self.status.emit(job.row, "Processing")
                source = Path(job.source)
                try:
                    self._report_progress(job.row, job_index, 10)
                    parsed = parse_pdf(source, self._cancel_event)
                    if self._cancel_event.is_set():
                        raise CancelledError()
                    self._report_progress(job.row, job_index, 45)
                    output_dir = Path(job.output_directory)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    dxf_path = output_dir / f"{job.output_stem}.dxf"
                    build_dxf(
                        parsed, dxf_path, self.rules, cancel_event=self._cancel_event
                    )
                    if self._cancel_event.is_set():
                        raise CancelledError()
                    self._report_progress(job.row, job_index, 80)
                    result_path = dxf_path
                    result_note = ""
                    if job.output_format == ".dwg":
                        try:
                            result_path = convert_dxf_to_dwg(
                                dxf_path,
                                output_dir / f"{job.output_stem}.dwg",
                                self._cancel_event,
                            )
                        except FileNotFoundError as exc:
                            result_note = f" (DWG unavailable; DXF fallback: {exc})"
                    if self._cancel_event.is_set():
                        raise CancelledError()
                    self._report_progress(job.row, job_index, 100)
                    warning = ""
                    if parsed.warnings:
                        details = "; ".join(parsed.warnings[:3])
                        remaining = len(parsed.warnings) - 3
                        if remaining > 0:
                            details += f"; and {remaining} more"
                        warning = f" (Warnings: {details})"
                    image_note = (
                        f"; raster assets: {job.output_stem}_assets"
                        if parsed.images
                        else ""
                    )
                    self.status.emit(
                        job.row,
                        f"Completed{warning}{result_note}{image_note}: {result_path.name}",
                    )
                except CancelledError:
                    self.status.emit(job.row, "Cancelled")
                    self.progress.emit(job.row, 0)
                    for remaining in self.jobs[job_index + 1:]:
                        self.status.emit(remaining.row, "Cancelled")
                        self.progress.emit(remaining.row, 0)
                    break
                except Exception as exc:
                    self.status.emit(job.row, f"Failed: {exc}")
                    self.progress.emit(job.row, 0)
                self.overall_progress.emit(
                    round((job_index + 1) * 100 / max(1, total))
                )
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """Responsive PDF conversion queue window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VectorBridge CAD Studio")
        self.resize(1100, 650)
        self.color_rules: list[ColorRule] = []
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        title = QLabel("VectorBridge CAD Studio")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.add_button = QPushButton("Add PDFs")
        self.settings_button = QPushButton("Color mapping")
        self.start_button = QPushButton("Start Conversion")
        self.abort_button = QPushButton("Abort")
        self.start_button.setDefault(True)
        self.abort_button.setEnabled(False)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.settings_button)
        toolbar.addWidget(self.start_button)
        toolbar.addWidget(self.abort_button)
        root.addLayout(toolbar)
        self.queue = QueueWidget()
        root.addWidget(self.queue)
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("Overall progress"))
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        progress_layout.addWidget(self.overall_progress_bar, 1)
        root.addLayout(progress_layout)
        self.output_label = QLabel("Output folder: same as each source PDF")
        self.output_button = QPushButton("Choose output folder")
        footer = QHBoxLayout()
        footer.addWidget(self.output_label)
        footer.addStretch()
        footer.addWidget(self.output_button)
        root.addLayout(footer)
        self.output_directory: str | None = None

        self.add_button.clicked.connect(self._choose_pdfs)
        self.queue.files_dropped.connect(self.queue.add_files)
        self.settings_button.clicked.connect(self._edit_settings)
        self.start_button.clicked.connect(self._start_conversion)
        self.abort_button.clicked.connect(self._abort_conversion)
        self.output_button.clicked.connect(self._choose_output_directory)
        self.statusBar().showMessage("Ready")

    def _choose_pdfs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add vector PDF files", "", "PDF files (*.pdf)"
        )
        self.queue.add_files(files)

    def _edit_settings(self) -> None:
        dialog = SettingsDialog(self.color_rules, self)
        if dialog.exec():
            self.color_rules = dialog.rules

    def _choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if directory:
            self.output_directory = directory
            self.output_label.setText(f"Output folder: {directory}")

    def _start_conversion(self) -> None:
        if self._thread is not None:
            return
        jobs: list[Job] = []
        reserved_outputs: set[tuple[str, str]] = set()
        for row in range(self.queue.rowCount()):
            status = self.queue.item(row, 2)
            source = self.queue.item(row, 1)
            if status is None or source is None or status.text() != "Pending":
                continue
            output_directory = self.output_directory or str(Path(source.text()).parent)
            source_stem = Path(source.text()).stem
            output_stem = source_stem
            suffix = 2
            while (
                (output_directory.casefold(), output_stem.casefold()) in reserved_outputs
                or (Path(output_directory) / f"{output_stem}.dxf").exists()
                or (Path(output_directory) / f"{output_stem}.dwg").exists()
            ):
                output_stem = f"{source_stem}_{suffix}"
                suffix += 1
            reserved_outputs.add((output_directory.casefold(), output_stem.casefold()))
            jobs.append(
                Job(
                    row,
                    source.text(),
                    self.queue.output_format(row),
                    output_directory,
                    output_stem,
                )
            )
        if not jobs:
            QMessageBox.information(self, "No pending files", "Add PDF files before starting.")
            return

        self.start_button.setEnabled(False)
        self.abort_button.setEnabled(True)
        self.overall_progress_bar.setValue(0)
        self._thread = QThread(self)
        self._worker = ConversionWorker(jobs, self.color_rules)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.queue.status)
        self._worker.progress.connect(self.queue.progress)
        self._worker.overall_progress.connect(self.overall_progress_bar.setValue)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._conversion_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self.statusBar().showMessage(f"Converting {len(jobs)} file(s)…")

    def _abort_conversion(self) -> None:
        if self._worker is not None and self._thread is not None:
            self._worker.cancel()
            self.abort_button.setEnabled(False)
            self.statusBar().showMessage("Aborting conversion…")

    @pyqtSlot()
    def _conversion_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        self.statusBar().showMessage("Batch finished")
        self._worker = None
        self._thread = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self,
                "Conversion in progress",
                "Wait for the current batch to finish before closing the application.",
            )
            event.ignore()
            return
        event.accept()
