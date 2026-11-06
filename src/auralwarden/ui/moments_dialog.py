from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from auralwarden.bookmarks import BookmarkStore, validated_seconds


def timestamp(seconds):
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d}"


class MomentsDialog(QDialog):
    def __init__(self, store: BookmarkStore, scope: Path, parent=None, *, elapsed_seconds=0):
        super().__init__(parent)
        self.store, self.scope = store, scope
        self.elapsed_seconds = elapsed_seconds
        self.setWindowTitle("Momentos guardados")
        self.setMinimumSize(660, 420)
        layout = QVBoxLayout(self)
        description = QLabel("Marcadores locales con hora y nota. No modifican la transcripción original.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.items = QListWidget()
        self.items.setWordWrap(True)
        layout.addWidget(self.items)
        actions = QHBoxLayout()
        add = QPushButton("Añadir marcador")
        add.clicked.connect(self.add_marker)
        delete = QPushButton("Eliminar seleccionado")
        delete.clicked.connect(self.delete_marker)
        actions.addWidget(add)
        actions.addWidget(delete)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.items.clear()
        try:
            for record in self.store.records(self.scope):
                item = QListWidgetItem(f"{timestamp(record['elapsed_seconds'])} · {record['note']}")
                item.setData(Qt.ItemDataRole.UserRole, record["id"])
                self.items.addItem(item)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "No se pudieron leer los marcadores", str(exc))

    def add_marker(self):
        value, accepted = QInputDialog.getText(self, "Hora del marcador", "Tiempo de la sesión (HH:MM:SS):",
                                              text=timestamp(self.elapsed_seconds))
        if not accepted:
            return
        try:
            parts = value.strip().split(":")
            if len(parts) != 3 or not all(part.isdecimal() for part in parts):
                raise ValueError("Usa el formato HH:MM:SS.")
            hours, minutes, seconds = map(int, parts)
            if minutes > 59 or seconds > 59:
                raise ValueError("Los minutos y segundos deben estar entre 00 y 59.")
            elapsed = validated_seconds(hours * 3600 + minutes * 60 + seconds)
            note, accepted = QInputDialog.getMultiLineText(self, "Nota del marcador", "Nota (hasta 1.000 caracteres):")
            if accepted:
                self.store.add(self.scope, elapsed, note)
                self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "No se pudo guardar el marcador", str(exc))

    def delete_marker(self):
        item = self.items.currentItem()
        if item is None:
            return
        if QMessageBox.question(self, "Eliminar marcador", "¿Eliminar este marcador?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(self.scope, item.data(Qt.ItemDataRole.UserRole))
            self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "No se pudo eliminar el marcador", str(exc))
