"""Color and layer remapping settings dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.builder import ColorRule


class SettingsDialog(QDialog):
    """Edit optional layer/RGB-to-ACI mapping rules."""

    def __init__(self, rules: list[ColorRule], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color mapping")
        self.resize(620, 340)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["PDF layer (optional)", "Source RGB #RRGGBB", "Target ACI (1-255)", "Target RGB #RRGGBB"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        for rule in rules:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rule.layer))
            rgb_text = ""
            if rule.rgb:
                rgb_text = "#{:02X}{:02X}{:02X}".format(*rule.rgb)
            self.table.setItem(row, 1, QTableWidgetItem(rgb_text))
            self.table.setItem(row, 2, QTableWidgetItem(str(rule.aci or "")))
            target_rgb = ""
            if rule.true_color:
                target_rgb = "#{:02X}{:02X}{:02X}".format(*rule.true_color)
            self.table.setItem(row, 3, QTableWidgetItem(target_rgb))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        add_button = QPushButton("Add rule")
        add_button.clicked.connect(self._add_row)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_rows)
        controls = QHBoxLayout()
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addStretch()
        controls.addWidget(buttons)
        layout.addLayout(controls)
        self.rules: list[ColorRule] = []

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column in range(4):
            self.table.setItem(row, column, QTableWidgetItem(""))

    def _remove_rows(self) -> None:
        for row in sorted({item.row() for item in self.table.selectedItems()}, reverse=True):
            self.table.removeRow(row)

    def _accept_if_valid(self) -> None:
        rules: list[ColorRule] = []
        try:
            for row in range(self.table.rowCount()):
                layer = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
                rgb_value = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
                aci_value = (self.table.item(row, 2).text() if self.table.item(row, 2) else "").strip()
                target_rgb_value = (
                    self.table.item(row, 3).text() if self.table.item(row, 3) else ""
                ).strip()
                if not layer and not rgb_value:
                    continue
                rgb = None
                if rgb_value:
                    rgb = self._parse_rgb(rgb_value, row + 1, "Source")
                aci = int(aci_value) if aci_value else None
                if aci is not None and not 1 <= aci <= 255:
                    raise ValueError(f"Row {row + 1}: ACI color must be from 1 to 255.")
                true_color = (
                    self._parse_rgb(target_rgb_value, row + 1, "Target")
                    if target_rgb_value
                    else None
                )
                if (aci is None) == (true_color is None):
                    raise ValueError(
                        f"Row {row + 1}: provide exactly one target color (ACI or RGB)."
                    )
                rules.append(
                    ColorRule(layer=layer, rgb=rgb, aci=aci, true_color=true_color)
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid color rule", str(exc))
            return
        self.rules = rules
        self.accept()

    @staticmethod
    def _parse_rgb(value: str, row: int, label: str) -> tuple[int, int, int]:
        rgb = value.removeprefix("#")
        if len(rgb) != 6:
            raise ValueError(f"Row {row}: {label} RGB must be #RRGGBB.")
        try:
            return tuple(int(rgb[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError as exc:
            raise ValueError(f"Row {row}: {label} RGB must be #RRGGBB.") from exc
