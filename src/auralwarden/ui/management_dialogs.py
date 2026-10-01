from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from auralwarden.alert_history import AlertHistoryStore
from auralwarden.models import AppSettings
from auralwarden.presets import ConfigurationPreset, PresetStore
from auralwarden.transcript_archive import (
    ArchivedTranscript,
    discover_archived_transcripts,
    load_archived_transcript,
)
from auralwarden.ui.widgets import aw_icon


class PresetDialog(QDialog):
    def __init__(
        self,
        store: PresetStore,
        current: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.current = current
        self.selected_name = ""
        self.setWindowTitle("Presets de configuración")
        self.setMinimumSize(520, 410)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Los presets incluidos cambian el equilibrio de reconocimiento. Puedes guardar tus propias hotwords y opciones sin almacenar el enlace ni el dispositivo de audio."
        )
        description.setWordWrap(True)
        description.setProperty("muted", True)
        layout.addWidget(description)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._apply())
        layout.addWidget(self.list_widget, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setProperty("muted", True)
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        self.save_button = QPushButton("Guardar configuración actual")
        self.save_button.setIcon(aw_icon("fa6s.floppy-disk"))
        self.save_button.clicked.connect(self._save_current)
        self.delete_button = QPushButton("Eliminar")
        self.delete_button.setIcon(aw_icon("fa6s.trash"))
        self.delete_button.setProperty("danger", True)
        self.delete_button.clicked.connect(self._delete_selected)
        self.apply_button = QPushButton("Aplicar")
        self.apply_button.setIcon(aw_icon("fa6s.check", "#ffffff"))
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.save_button)
        actions.addStretch()
        actions.addWidget(self.delete_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._presets: list[ConfigurationPreset] = []
        self._reload()

    def _reload(self, select_name: str = "") -> None:
        self._presets = self.store.list()
        self.list_widget.clear()
        selected_row = 0
        for index, preset in enumerate(self._presets):
            suffix = " · incluido" if preset.built_in else " · personal"
            self.list_widget.addItem(preset.name + suffix)
            if preset.name.casefold() == select_name.casefold():
                selected_row = index
        if self._presets:
            self.list_widget.setCurrentRow(selected_row)

    def _selected(self) -> ConfigurationPreset | None:
        row = self.list_widget.currentRow()
        return self._presets[row] if 0 <= row < len(self._presets) else None

    def _selection_changed(self, _row: int) -> None:
        selected = self._selected()
        self.apply_button.setEnabled(selected is not None)
        self.delete_button.setEnabled(bool(selected and not selected.built_in))
        if selected is None:
            self.detail.clear()
        elif selected.built_in:
            self.detail.setText("Preset incluido. Conserva la fuente y las hotwords actuales.")
        else:
            self.detail.setText(
                f"Preset personal actualizado: {selected.updated_at or 'sin fecha'}."
            )

    def _save_current(self) -> None:
        name, accepted = QInputDialog.getText(self, "Guardar preset", "Nombre")
        if not accepted:
            return
        try:
            saved = self.store.save(name, self.current)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self._reload(saved.name)

    def _delete_selected(self) -> None:
        selected = self._selected()
        if selected is None or selected.built_in:
            return
        answer = QMessageBox.question(
            self,
            "Eliminar preset",
            f"¿Eliminar el preset “{selected.name}”?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(selected.name)
        self._reload()

    def _apply(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        self.selected_name = selected.name
        self.accept()


class AlertHistoryDialog(QDialog):
    def __init__(
        self,
        store: AlertHistoryStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._records = store.records()
        self._visible_records: list[dict] = []
        self.setWindowTitle("Historial de alertas")
        self.setMinimumSize(900, 560)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar hotword, hablante, fuente o contexto")
        self.search.textChanged.connect(self._refresh)
        self.evidence_filter = QComboBox()
        self.evidence_filter.addItem("Todas las alertas", "all")
        self.evidence_filter.addItem("Con vídeo", "video")
        self.evidence_filter.addItem("Con audio", "audio")
        self.evidence_filter.addItem("Sin evidencia", "none")
        self.evidence_filter.currentIndexChanged.connect(self._refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.evidence_filter)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Hotword", "Hablante", "Confianza", "Fuente", "Evidencia"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._open_evidence())
        layout.addWidget(self.table, 1)
        self.context = QTextEdit()
        self.context.setReadOnly(True)
        self.context.setMaximumHeight(95)
        self.context.setPlaceholderText("Selecciona una alerta para leer su contexto.")
        layout.addWidget(self.context)
        actions = QHBoxLayout()
        self.total = QLabel()
        self.total.setProperty("muted", True)
        self.open_button = QPushButton("Abrir evidencia")
        self.open_button.setIcon(aw_icon("fa6s.play"))
        self.open_button.clicked.connect(self._open_evidence)
        self.folder_button = QPushButton("Abrir carpeta")
        self.folder_button.setIcon(aw_icon("fa6s.folder-open"))
        self.folder_button.clicked.connect(self._open_folder)
        self.clear_button = QPushButton("Vaciar historial")
        self.clear_button.setIcon(aw_icon("fa6s.trash"))
        self.clear_button.setProperty("danger", True)
        self.clear_button.clicked.connect(self._clear)
        actions.addWidget(self.total)
        actions.addStretch()
        actions.addWidget(self.open_button)
        actions.addWidget(self.folder_button)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self, *_: object) -> None:
        query = " ".join(self.search.text().casefold().split())
        evidence = str(self.evidence_filter.currentData() or "all")
        visible = []
        for record in self._records:
            searchable = " ".join(
                str(record.get(key) or "")
                for key in ("phrase", "speaker_id", "source", "context", "matched_text")
            ).casefold()
            has_audio = bool(record.get("audio_clip"))
            has_video = bool(record.get("video_clip"))
            if query and query not in searchable:
                continue
            if evidence == "audio" and not has_audio:
                continue
            if evidence == "video" and not has_video:
                continue
            if evidence == "none" and (has_audio or has_video):
                continue
            visible.append(record)
        self._visible_records = visible
        self.table.setRowCount(len(visible))
        for row, record in enumerate(visible):
            detected = str(record.get("detected_at") or "")
            try:
                detected = datetime.fromisoformat(detected).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            media = []
            if record.get("video_clip"):
                media.append("Vídeo")
            if record.get("audio_clip"):
                media.append("Audio")
            values = (
                detected,
                str(record.get("phrase") or ""),
                str(record.get("speaker_id") or "—"),
                f"{float(record.get('score') or 0):.0f} %",
                str(record.get("source") or "—"),
                " + ".join(media) or "Sin clip",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.total.setText(f"{len(visible)} de {len(self._records)} alertas")
        if visible:
            self.table.selectRow(0)
        else:
            self.context.clear()
            self.open_button.setEnabled(False)
            self.folder_button.setEnabled(False)

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        return self._visible_records[row] if 0 <= row < len(self._visible_records) else None

    def _selection_changed(self) -> None:
        record = self._selected()
        self.context.setPlainText(str(record.get("context") or "") if record else "")
        path = self._evidence_path(record)
        self.open_button.setEnabled(bool(path and path.is_file()))
        folder = self._folder_path(record)
        self.folder_button.setEnabled(bool(folder and folder.is_dir()))

    @staticmethod
    def _evidence_path(record: dict | None) -> Path | None:
        if not record:
            return None
        for key in ("video_clip", "audio_clip"):
            value = str(record.get(key) or "")
            if value:
                return Path(value)
        return None

    @staticmethod
    def _folder_path(record: dict | None) -> Path | None:
        evidence = AlertHistoryDialog._evidence_path(record)
        if evidence is not None:
            return evidence.parent
        session = str((record or {}).get("session_path") or "")
        return Path(session) if session else None

    def _open_evidence(self) -> None:
        path = self._evidence_path(self._selected())
        if path is not None and path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _open_folder(self) -> None:
        path = self._folder_path(self._selected())
        if path is not None and path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _clear(self) -> None:
        if not self._records:
            return
        answer = QMessageBox.question(
            self,
            "Vaciar historial",
            "¿Eliminar el índice local de alertas? Los clips y las transcripciones no se borrarán.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.clear()
        self._records = []
        self._refresh()


class TranscriptLibraryDialog(QDialog):
    def __init__(
        self,
        sessions_root: Path | Iterable[Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sessions_roots = (
            [sessions_root]
            if isinstance(sessions_root, Path)
            else list(sessions_root)
        )
        records_by_path: dict[Path, ArchivedTranscript] = {}
        for root in self.sessions_roots:
            for record in discover_archived_transcripts(root):
                records_by_path[record.path.resolve()] = record
        self._records = sorted(
            records_by_path.values(),
            key=lambda item: (item.started_at, item.path.name),
            reverse=True,
        )
        self._visible_records: list[ArchivedTranscript] = []
        self._current_path: Path | None = None
        self.setWindowTitle("Transcripciones anteriores")
        self.setMinimumSize(980, 620)
        layout = QVBoxLayout(self)

        description = QLabel(
            "Lee las transcripciones guardadas sin abrir el JSON. "
            "También puedes elegir un TXT, JSON o diario de recuperación antiguo."
        )
        description.setWordWrap(True)
        description.setProperty("muted", True)
        layout.addWidget(description)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por título, fecha o archivo")
        self.search.textChanged.connect(self._refresh)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._selection_changed)
        self.total = QLabel()
        self.total.setProperty("muted", True)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.list_widget, 1)
        left_layout.addWidget(self.total)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.title_label = QLabel("Selecciona una transcripción")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setProperty("title", True)
        self.detail_label = QLabel()
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("muted", True)
        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setPlaceholderText(
            "Selecciona una transcripción de la lista o abre un archivo antiguo."
        )
        right_layout.addWidget(self.title_label)
        right_layout.addWidget(self.detail_label)
        right_layout.addWidget(self.viewer, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([330, 650])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.choose_button = QPushButton("Abrir otro archivo")
        self.choose_button.setIcon(aw_icon("fa6s.file-import"))
        self.choose_button.setToolTip(
            "Leer dentro de AuralWarden una transcripción TXT, JSON o JSONL de otra carpeta"
        )
        self.choose_button.clicked.connect(self._choose_file)
        self.folder_button = QPushButton("Abrir carpeta")
        self.folder_button.setIcon(aw_icon("fa6s.folder-open"))
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.choose_button)
        actions.addStretch()
        actions.addWidget(self.folder_button)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self, *_: object) -> None:
        query = " ".join(self.search.text().casefold().split())
        self._visible_records = [
            record
            for record in self._records
            if not query
            or query
            in " ".join(
                (record.title, record.display_date, record.path.name)
            ).casefold()
        ]
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for record in self._visible_records:
            item = QListWidgetItem(record.label)
            item.setToolTip(str(record.path))
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self.total.setText(
            f"{len(self._visible_records)} de {len(self._records)} transcripciones"
        )
        if self._visible_records:
            self.list_widget.setCurrentRow(0)
            self._selection_changed(0)
        else:
            self._show_empty()

    def _selection_changed(self, row: int) -> None:
        if not 0 <= row < len(self._visible_records):
            self._show_empty()
            return
        self.open_path(self._visible_records[row].path, self._visible_records[row])

    def open_path(
        self,
        path: Path,
        record: ArchivedTranscript | None = None,
    ) -> bool:
        try:
            text, entries = load_archived_transcript(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "No se pudo abrir", str(exc))
            return False
        resolved = path.expanduser().resolve()
        self._current_path = resolved
        self.title_label.setText(record.title if record else resolved.stem)
        detail = record.display_date if record else "Archivo seleccionado manualmente"
        if entries:
            detail += f" · {len(entries)} fragmentos"
        detail += f"\n{resolved}"
        self.detail_label.setText(detail)
        self.detail_label.setToolTip(str(resolved))
        self.viewer.setPlainText(text)
        self.viewer.moveCursor(QTextCursor.MoveOperation.Start)
        self.folder_button.setEnabled(True)
        return True

    def _choose_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir transcripción",
            str(self.sessions_roots[0] if self.sessions_roots else Path.home()),
            "Transcripciones (*.txt *.json *.jsonl);;Todos los archivos (*.*)",
        )
        if selected:
            self.open_path(Path(selected))

    def _open_folder(self) -> None:
        if self._current_path is not None and self._current_path.parent.is_dir():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._current_path.parent.resolve()))
            )

    def _show_empty(self) -> None:
        self._current_path = None
        self.title_label.setText("Sin transcripciones guardadas")
        self.detail_label.setText(
            "Guarda una sesión o usa “Abrir otro archivo” para leer una transcripción antigua."
        )
        self.viewer.clear()
        self.folder_button.setEnabled(False)
