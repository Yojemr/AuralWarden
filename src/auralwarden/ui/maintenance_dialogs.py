from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QDateTime, QFile, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from auralwarden.stop_timer import StopTimer
from auralwarden.storage import LABELS, scan_storage, validate_storage_file
from auralwarden.ui.typography import justify_label


class StopTimerDialog(QDialog):
    def __init__(self, timer: StopTimer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Temporizador de detención")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        description = QLabel("Detiene el monitoreo y finaliza las grabaciones de forma normal. No cierra Windows ni borra la transcripción. Funciona también desde la bandeja; no funciona con el PC apagado ni despierta Windows.")
        justify_label(description)
        layout.addWidget(description)
        self.mode = QComboBox()
        self.mode.addItems(["Sin temporizador", "Después de iniciar · duración", "A una fecha y hora"])
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 7 * 24 * 60)
        self.minutes.setSuffix(" minutos")
        self.minutes.setValue(int((timer.duration_seconds or 3600) / 60))
        self.minutes.setToolTip("La duración empieza al iniciar el monitoreo, o desde ahora si ya está activo. Incluye esperas y reconexiones.")
        self.at = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.at.setCalendarPopup(True)
        self.at.setStyleSheet("QDateTimeEdit {background:#10232e;color:#dce7ec;border:1px solid #294653;padding:7px;} QDateTimeEdit:disabled {background:#10202a;color:#82939c;}")
        self.at.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.at.setToolTip("Hora local de Windows. Si el PC está suspendido, la detención se solicita al reanudar.")
        if timer.stop_at_epoch is not None:
            self.at.setDateTime(QDateTime.fromSecsSinceEpoch(int(timer.stop_at_epoch)))
        self.mode.setCurrentIndex(1 if timer.duration_seconds else 2 if timer.stop_at_epoch else 0)
        self.mode.currentIndexChanged.connect(self._enable)
        for widget in (self.mode, self.minutes, self.at):
            layout.addWidget(widget)
        self._enable()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aplicar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _enable(self):
        self.minutes.setEnabled(self.mode.currentIndex() == 1)
        self.at.setEnabled(self.mode.currentIndex() == 2)

    def apply_to(self, timer):
        timer.configure(duration_seconds=self.minutes.value() * 60 if self.mode.currentIndex() == 1 else None,
                        stop_at_epoch=self.at.dateTime().toSecsSinceEpoch() if self.mode.currentIndex() == 2 else None)


class StorageScan(QThread):
    ready = Signal(object)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        try:
            self.ready.emit((scan_storage(self.root, cancelled=self.isInterruptionRequested), None))
        except (OSError, ValueError) as exc:
            self.ready.emit((None, str(exc)))


class StorageDialog(QDialog):
    def __init__(self, root: Path, can_modify, parent=None):
        super().__init__(parent)
        self.root, self.can_modify = root, can_modify
        self.records = []
        self.worker = None
        self._pending_close = None
        self.setWindowTitle("Almacenamiento de AuralWarden")
        self.resize(930, 610)
        layout = QVBoxLayout(self)
        description = QLabel("Selecciona archivos personales para enviarlos a la Papelera. No hay borrado automático. Modelos, componentes, configuración y material de recuperación están protegidos.")
        justify_label(description)
        layout.addWidget(description)
        self.summary = QLabel("Analizando…")
        justify_label(self.summary)
        layout.addWidget(self.summary)
        self.category = QComboBox()
        self.category.addItem("Todas las categorías", "")
        for key, label in LABELS.items():
            self.category.addItem(label, key)
        self.category.currentIndexChanged.connect(self.populate)
        layout.addWidget(self.category)
        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet("QTableWidget {background:#0c1f29;color:#dce7ec;gridline-color:#29404b;} QHeaderView::section,QTableCornerButton::section {background:#10232e;color:#9cacb5;border:1px solid #29404b;padding:5px;} QScrollBar:vertical {background:#0b1b24;width:10px;} QScrollBar:horizontal {background:#0b1b24;height:10px;} QScrollBar::handle {background:#365561;min-height:24px;min-width:24px;} QScrollBar::add-line,QScrollBar::sub-line {height:0px;width:0px;} QScrollBar::add-page,QScrollBar::sub-page {background:#0b1b24;}")
        self.table.setHorizontalHeaderLabels(["Archivo", "Categoría", "Tamaño"])
        self.table.setColumnWidth(0, 570)
        self.table.setColumnWidth(1, 185)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.refresh_button = QPushButton("Actualizar análisis")
        self.refresh_button.clicked.connect(self.refresh)
        folder = QPushButton("Abrir carpeta de datos")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))))
        self.trash_button = QPushButton("Enviar seleccionados a la Papelera")
        self.trash_button.clicked.connect(self.move_selected)
        row.addWidget(self.refresh_button)
        row.addWidget(folder)
        row.addWidget(self.trash_button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.trash_button.setEnabled(False)
        self.worker = StorageScan(self.root, self)
        self.worker.ready.connect(self._loaded)
        self.worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _loaded(self, result):
        outcome, error = result
        if error:
            self.summary.setText(error)
            return
        self.records, complete = outcome
        totals = {key: sum(item.size for item in self.records if item.category == key) for key in LABELS}
        used = " · ".join(f"{LABELS[key]}: {value / 1024**2:.1f} MiB" for key, value in totals.items() if value)
        try:
            free = f"{shutil.disk_usage(self.root).free / 1024**3:.1f} GiB"
        except OSError:
            free = "no disponible"
        self.summary.setText(f"Libre en la unidad: {free}\n{used}" +
                             ("\nAnálisis parcial: se omitieron enlaces, carpetas inaccesibles o se alcanzó el límite." if not complete else ""))
        self.populate()

    def populate(self):
        category = self.category.currentData()
        self.table.setRowCount(0)
        for record in self.records:
            if category and record.category != category:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(record.relative)
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(LABELS[record.category]))
            self.table.setItem(row, 2, QTableWidgetItem(f"{record.size / 1024**2:.2f} MiB"))
        self.trash_button.setEnabled(bool(self.can_modify()))
        self.trash_button.setToolTip("Detén el monitoreo antes de limpiar. Los archivos cambiados o protegidos no se eliminan.")

    def move_selected(self):
        if not self.can_modify():
            QMessageBox.information(self, "Monitoreo activo", "Detén el monitoreo antes de modificar archivos.")
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        selected = [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in rows]
        if not selected:
            return
        try:
            for item in selected:
                validate_storage_file(self.root, item)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Selección protegida o modificada", str(exc))
            return
        if QMessageBox.question(self, "Confirmar envío a la Papelera",
            f"¿Enviar {len(selected)} archivos ({sum(item.size for item in selected) / 1024**2:.1f} MiB) a la Papelera?\n\nPodrás recuperarlos desde Windows. La operación puede completarse solo parcialmente si un archivo está ocupado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        completed = 0
        try:
            for item in selected:
                if not self.can_modify():
                    raise ValueError("El monitoreo se activó; se detuvo la limpieza.")
                path = validate_storage_file(self.root, item)
                result = QFile.moveToTrash(str(path))
                if not (result[0] if isinstance(result, tuple) else result):
                    raise OSError("Windows no pudo enviar el archivo a la Papelera. No se borra permanentemente.")
                completed += 1
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Limpieza parcial", f"{completed} archivos enviados a la Papelera.\n{exc}")
        self.refresh()

    def done(self, result):
        if self.worker is not None and self.worker.isRunning():
            self._pending_close = result
            self.worker.requestInterruption()
            self.summary.setText("Terminando el análisis…")
            return
        super().done(result)

    def _finished(self):
        if self._pending_close is not None:
            super().done(self._pending_close)
