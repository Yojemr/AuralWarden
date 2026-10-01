from __future__ import annotations

import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from auralwarden import __version__
from auralwarden.alert_history import AlertHistoryStore
from auralwarden.captions import is_youtube_source
from auralwarden.filenames import date_time_label
from auralwarden.local_control import (
    CONTROL_PROTOCOL_VERSION,
    LocalControlAuditStore,
    LocalControlCredentialStore,
    redact_source,
    redact_text,
    request_fingerprint,
)
from auralwarden.migration import (
    MigrationResult,
    find_previous_portable_installations,
    migrate_latest_portable_installation,
)
from auralwarden.models import AppSettings, EngineEvent, EventKind, Hotword, SessionState
from auralwarden.model_installer import initialize_data_layout
from auralwarden.model_catalog import discover_local_whisper_models
from auralwarden.ui.setup_dialog import ModelSetupDialog
from auralwarden.paths import application_root, portable_mode, sessions_dir, transcripts_dir
from auralwarden.presets import PresetStore
from auralwarden.runtime_status import RuntimeStatusStore
from auralwarden.settings_store import SettingsStore
from auralwarden.session_recovery import discard_recovery, find_recoverable_transcripts
from auralwarden.speaker_profiles import SpeakerProfileStore
from auralwarden.source_info import SourceInfo, fallback_source_info
from auralwarden.ui.assets import asset_path
from auralwarden.ui.controller import MonitoringController
from auralwarden.ui.dialogs import PreferencesDialog, SpeakerNamesDialog
from auralwarden.ui.management_dialogs import (
    AlertHistoryDialog,
    PresetDialog,
    TranscriptLibraryDialog,
)
from auralwarden.ui.preview import PreviewSession
from auralwarden.ui.source_info import SourceInfoSession
from auralwarden.ui.widgets import (
    ActivityFeed,
    HotwordEditor,
    PreviewPanel,
    QuickSettingsPanel,
    ResourcePanel,
    TranscriptFeed,
    aw_icon,
)
from auralwarden.ui.styles import scaled_stylesheet
from auralwarden.windows_audio import (
    SilentMonitoringManager,
    WindowsAudioError,
    list_windows_audio_devices,
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        demo: bool = False,
        settings_store: SettingsStore | None = None,
        controller: MonitoringController | None = None,
        runtime_status_store: RuntimeStatusStore | None = None,
    ) -> None:
        super().__init__()
        self.demo_requested = demo
        self.store = settings_store or SettingsStore()
        initialize_data_layout(self.store.path.parent)
        self.runtime_status = runtime_status_store or RuntimeStatusStore(
            self.store.path.with_name("runtime-status.json")
        )
        first_launch = not self.store.path.exists()
        self._migration_result: MigrationResult | None = None
        if first_launch and settings_store is None and portable_mode():
            self._migration_result = migrate_latest_portable_installation(
                application_root(), self.store.path.parent
            )
            first_launch = not self.store.path.exists()
        self.settings = self.store.load()
        self.presets = PresetStore(self.store.path.with_name("presets.json"))
        self.alert_history = AlertHistoryStore(
            self.store.path.with_name("alert-history.json")
        )
        self.local_control_credentials = LocalControlCredentialStore(
            self.store.path.with_name("local-control.json")
        )
        self.local_control_audit = LocalControlAuditStore(
            self.store.path.with_name("local-control-audit.json")
        )
        self.speaker_profiles = SpeakerProfileStore(
            self.store.path.with_name("speaker-profiles.json")
        )
        if first_launch:
            self.settings.source_url = ""
            self.settings.hotwords = []
            self.settings.diarization_enabled = False
        if demo:
            self.settings.source_url = "demo://interfaz"
            self.settings.hotwords = [
                Hotword("licitación", threshold=88),
                Hotword("ayuda", threshold=85),
                Hotword("contrato", threshold=88),
            ]
            self.settings.transcription_window_seconds = 3.0
            self.settings.transcription_overlap_seconds = 0.0
            self.settings.diarization_enabled = False
            self.settings.save_event_video_clips = False
            self.settings.save_full_video = False
            self.settings.use_youtube_captions = False
            self.settings.clip_pre_seconds = 2
            self.settings.clip_post_seconds = 2
        if self.settings.allow_local_control:
            self.local_control_credentials.ensure()
        self.controller = controller or MonitoringController(parent=self)
        self.controller.event_received.connect(self._handle_event)
        self.preview = PreviewSession(self)
        self.preview.frame_ready.connect(self.preview_panel_set_frame)
        self.preview.status_changed.connect(self._preview_status)
        self.preview.error.connect(self._preview_error)
        self.source_info = SourceInfoSession(self)
        self.source_info.ready.connect(self._source_info_ready)
        self._started_monotonic: float | None = None
        self._stopped_elapsed: int | None = None
        self._current_state = SessionState.IDLE
        self._status_detail = "Aplicación abierta; no hay una sesión activa."
        self._current_source_title = (
            self.settings.source_title
            or fallback_source_info(self.settings.source_url).title
        )
        self._last_match = "Sin coincidencias"
        self._clip_count = 0
        self._clip_events: set[str] = set()
        self._speakers: set[str] = set()
        self._speaker_displays: dict[str, str] = {}
        self._quitting = False
        self._close_pending = False
        self._muted = False
        self._last_audio_level = 0.0
        self.silent_audio = SilentMonitoringManager(
            self.store.path.with_name("silent-audio-state.json")
        )
        self._silent_recovery_error = ""
        self._silent_recovery_attempts = 0
        try:
            self._recovered_silent_audio = self.silent_audio.recover_interrupted()
        except Exception as exc:
            self._recovered_silent_audio = False
            self._silent_recovery_error = str(exc)
        self._hotword_update_timer = QTimer(self)
        self._hotword_update_timer.setSingleShot(True)
        self._hotword_update_timer.setInterval(300)
        self._hotword_update_timer.timeout.connect(self._apply_hotword_changes)
        self._build_ui()
        self._apply_settings_to_controls()
        self._apply_interface_scale()
        self._create_tray()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_elapsed)
        self._clock.start(1_000)
        self._audio_guard = QTimer(self)
        self._audio_guard.timeout.connect(self._check_silent_audio_state)
        self._audio_guard.start(1_000)
        self._state_guard = QTimer(self)
        self._state_guard.setInterval(2_500)
        self._state_guard.timeout.connect(self._synchronize_controller_state)
        self._state_guard.start()
        self.setWindowTitle("AuralWarden — monitoreo local")
        self.setWindowIcon(QIcon(str(asset_path("app-icon.ico"))))
        self.resize(1488, 980)
        self._write_runtime_status()
        if self._recovered_silent_audio:
            QTimer.singleShot(
                250,
                lambda: QMessageBox.information(
                    self,
                    "Audio restaurado",
                    "AuralWarden restauró el audio que había quedado silenciado por una ejecución anterior.",
                ),
            )
        elif self._silent_recovery_error:
            self._status_detail = "No se pudo restaurar la salida de audio; se volverá a intentar."
            self.status_label.setToolTip(self._status_detail)
            QTimer.singleShot(250, lambda: QMessageBox.warning(
                self, "Restauración de audio pendiente",
                "Windows no permitió restaurar la salida. AuralWarden lo intentará de nuevo; "
                "también puedes usar el control de volumen de Windows.",
            ))
        if self._migration_result is not None:
            QTimer.singleShot(350, self._show_migration_result)
        if not demo:
            QTimer.singleShot(500, self._offer_transcript_recovery)
            if first_launch and settings_store is None:
                QTimer.singleShot(800, self._offer_initial_setup)
        if demo:
            QTimer.singleShot(350, self.start_monitoring)

    def _offer_initial_setup(self) -> None:
        if not self.controller.running and not discover_local_whisper_models():
            self.open_model_setup()

    def open_model_setup(self) -> None:
        if self.controller.running:
            return
        dialog = ModelSetupDialog(self.settings, self, root=self.store.path.parent)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.settings.model_name = dialog.installed_model
        if dialog.speaker_paths:
            self.settings.diarization_enabled = True
            self.settings.diarization_segmentation_model = str(dialog.speaker_paths["segmentation"])
            self.settings.diarization_embedding_model = str(dialog.speaker_paths["embedding"])
        self.store.save(self.settings)
        self._apply_settings_to_controls()

    def _show_migration_result(self) -> None:
        result = self._migration_result
        if result is None:
            return
        model_detail = (
            f"Se reutilizaron {result.linked_files} archivos sin duplicar su espacio."
            if result.linked_files
            else "No se encontraron modelos que pudieran reutilizarse sin copiarlos."
        )
        profile_detail = (
            "Los perfiles de voz voluntarios también se conservaron localmente."
            if result.speaker_profiles_imported
            else "No había perfiles de voz que migrar."
        )
        preference_detail = (
            "También se conservaron los presets y el historial local disponibles."
            if result.presets_imported or result.alert_history_imported
            else "No había presets ni historial de alertas que migrar."
        )
        QMessageBox.information(
            self,
            "Configuración migrada",
            f"AuralWarden importó la configuración de {result.source_root.name}.\n\n"
            f"{model_detail}\n{profile_detail}\n{preference_detail}\n\n"
            "No se importaron clips, grabaciones, sesiones ni transcripciones.",
        )

    def _offer_transcript_recovery(self) -> None:
        if self.controller.running or self.controller.transcript_dirty:
            return
        root = self.store.path.parent / "sessions"
        recoveries = find_recoverable_transcripts(root)
        if not recoveries:
            return
        recovery = recoveries[0]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle("Transcripción recuperable")
        box.setText(
            "AuralWarden encontró texto de una sesión que no terminó normalmente."
        )
        box.setInformativeText(
            f"{recovery.title or recovery.session_path.name}\n"
            f"{len(recovery.entries)} fragmentos disponibles.\n\n"
            "Puedes restaurarlos en la pantalla y guardarlos como archivo de texto."
        )
        restore = box.addButton("Restaurar", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is discard:
            discard_recovery(recovery)
            return
        if box.clickedButton() is not restore:
            return
        self.controller.restore_recovered_transcript(recovery)
        self.transcript.clear()
        self._speakers.clear()
        self._speaker_displays.clear()
        for entry in recovery.entries:
            payload = asdict(entry)
            self.transcript.append_entry(payload)
            self._speakers.add(entry.speaker_id)
            self._speaker_displays[entry.speaker_id] = entry.speaker_id
        self.session_label.setText(f"Recuperada: {recovery.session_path.name}")
        self.session_label.setToolTip(str(recovery.session_path))
        self._status_detail = "Transcripción recuperada; guárdala antes de iniciar otra sesión."
        self.status_label.setToolTip(self._status_detail)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 10, 12, 8)
        root_layout.setSpacing(9)
        root_layout.addLayout(self._build_header())

        body = QGridLayout()
        body.setHorizontalSpacing(9)
        body.setVerticalSpacing(9)
        body.setColumnStretch(0, 31)
        body.setColumnStretch(1, 48)
        body.setColumnStretch(2, 21)
        body.setRowStretch(0, 70)
        body.setRowStretch(1, 30)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(9)
        self.preview_panel = PreviewPanel()
        self.preview_panel.open_requested.connect(self.open_source)
        self.preview_panel.toggle_requested.connect(self.toggle_preview)
        self.resources = ResourcePanel()
        left_layout.addWidget(self.preview_panel, 43)
        left_layout.addWidget(self.resources, 57)
        body.addWidget(left, 0, 0)

        self.transcript = TranscriptFeed()
        self.caption_preview = self.transcript.caption_preview
        body.addWidget(self.transcript, 0, 1)
        self.activity = ActivityFeed()
        self.activity.open_requested.connect(self._open_evidence)
        body.addWidget(self.activity, 0, 2, 2, 1)

        lower = QWidget()
        lower_layout = QHBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(9)
        self.hotword_editor = HotwordEditor()
        self.hotword_editor.changed.connect(self._queue_hotword_update)
        self.quick_settings = QuickSettingsPanel()
        self.quick_settings.save_event_clips.toggled.connect(self._apply_clip_switches)
        self.quick_settings.save_event_video_clips.toggled.connect(self._apply_clip_switches)
        self.quick_settings.preferences_requested.connect(self.open_preferences)
        self.quick_settings.test_sound_requested.connect(self.test_notification_sound)
        self.quick_settings.test_notification_requested.connect(self.test_notification)
        self.quick_settings.use_youtube_captions.toggled.connect(
            self._update_caption_preview_visibility
        )
        lower_layout.addWidget(self.hotword_editor, 55)
        lower_layout.addWidget(self.quick_settings, 45)
        body.addWidget(lower, 1, 0, 1, 2)
        root_layout.addLayout(body, 1)
        root_layout.addLayout(self._build_footer())
        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        brand = QWidget()
        brand.setFixedWidth(280)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(4, 0, 10, 0)
        brand_layout.setSpacing(8)
        mark = QLabel()
        mark_pixmap = QPixmap(str(asset_path("brand-mark.png")))
        mark.setPixmap(
            mark_pixmap.scaled(
                66,
                40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        wordmark = QLabel(
            '<span style="color:#7fe3c4;font-weight:350;">Aural</span>'
            '<span style="color:#edf3f5;font-weight:700;">Warden</span>'
        )
        wordmark.setTextFormat(Qt.TextFormat.RichText)
        wordmark.setStyleSheet("font-size:23px;")
        brand_layout.addWidget(mark)
        brand_layout.addWidget(wordmark)
        brand_layout.addStretch()
        header.addWidget(brand)

        source_frame = QFrame()
        source_frame.setProperty("card", True)
        source_layout = QHBoxLayout(source_frame)
        source_layout.setContentsMargins(10, 4, 5, 4)
        self.source_icon = QLabel()
        self.source_icon.setPixmap(aw_icon("fa6s.link", "#aebdc4").pixmap(20, 20))
        self.source_kind = QComboBox()
        self.source_kind.setMinimumWidth(150)
        self.source_kind.addItem("Enlace", "url")
        self.source_kind.addItem("Audio del sistema", "system_audio")
        self.source_kind.addItem("Micrófono", "microphone")
        self.source_kind.setToolTip(
            "Elige entre una transmisión o archivo, todo el audio reproducido por Windows, o un micrófono."
        )
        self.source_kind.currentIndexChanged.connect(self._source_kind_changed)
        self.source_input = QLineEdit()
        self.source_input.setObjectName("sourceInput")
        self.source_input.setPlaceholderText("Pega un enlace compatible o selecciona un archivo")
        self.source_input.setStyleSheet("border:none;background:transparent;")
        self.source_input.setToolTip(
            "Enlace de YouTube, Twitch, Kick, radio o ruta de un archivo local"
        )
        self.source_input.editingFinished.connect(self._request_source_title)
        self.source_device = QComboBox()
        self.source_device.setMinimumWidth(220)
        self.source_device.setToolTip("Dispositivo local que AuralWarden analizará")
        self.source_device.currentIndexChanged.connect(self._source_device_changed)
        self.source_device.hide()
        self.source_browse = QPushButton()
        self.source_browse.setIcon(aw_icon("fa6s.folder-open", "#aebdc4"))
        self.source_browse.setProperty("flat", True)
        self.source_browse.setToolTip("Seleccionar archivo local")
        self.source_browse.clicked.connect(self._browse_source)
        self.source_refresh = QPushButton()
        self.source_refresh.setIcon(aw_icon("fa6s.rotate", "#aebdc4"))
        self.source_refresh.setProperty("flat", True)
        self.source_refresh.setToolTip("Actualizar la lista de dispositivos de audio")
        self.source_refresh.clicked.connect(self._refresh_audio_devices)
        self.source_refresh.hide()
        source_layout.addWidget(self.source_icon)
        source_layout.addWidget(self.source_kind)
        source_layout.addWidget(self.source_input, 1)
        source_layout.addWidget(self.source_device, 1)
        source_layout.addWidget(self.source_browse)
        source_layout.addWidget(self.source_refresh)
        header.addWidget(source_frame, 1)

        self.start_button = QPushButton("Iniciar monitoreo")
        self.start_button.setObjectName("startButton")
        self.start_button.setIcon(aw_icon("fa6s.play", "white"))
        self.start_button.setProperty("primary", True)
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button = QPushButton("Detener")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setIcon(aw_icon("fa6s.stop", "#d8e0e4"))
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.stop_button.setEnabled(False)
        header.addWidget(self.start_button)
        header.addWidget(self.stop_button)

        self.silent_button = QPushButton("Silenciar salida")
        self.silent_button.setIcon(aw_icon("fa6s.volume-xmark", "#d8e0e4"))
        self.silent_button.setToolTip(
            "Silenciar temporalmente la salida mientras AuralWarden continúa analizándola"
        )
        self.silent_button.clicked.connect(self._toggle_silent_monitoring)
        self.silent_button.hide()
        self.silent_button.setEnabled(False)
        header.addWidget(self.silent_button)

        status_box = QWidget()
        status_box.setFixedWidth(245)
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(8, 0, 0, 0)
        status_layout.setSpacing(2)
        status_line = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(9, 9)
        self.status_dot.setStyleSheet("background:#657680;border-radius:4px;")
        self.status_label = QLabel("En espera")
        self.status_label.setProperty("title", True)
        status_line.addWidget(self.status_dot)
        status_line.addWidget(self.status_label)
        status_line.addStretch()
        self.session_label = QLabel("Todo se procesa localmente")
        self.session_label.setProperty("muted", True)
        self.session_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addLayout(status_line)
        status_layout.addWidget(self.session_label)
        header.addWidget(status_box)

        menu_button = QPushButton()
        menu_button.setIcon(aw_icon("fa6s.bars", "#aebdc4"))
        menu_button.setProperty("flat", True)
        menu_button.setToolTip("Preferencias, modelos e información legal")
        app_menu = QMenu(menu_button)
        preferences_action = app_menu.addAction(
            aw_icon("fa6s.gear", "#b8c8ce"), "Preferencias"
        )
        preferences_action.triggered.connect(self.open_preferences)
        models_action = app_menu.addAction(
            aw_icon("fa6s.download", "#b8c8ce"), "Preparar modelos"
        )
        models_action.triggered.connect(self.open_model_setup)
        app_menu.addSeparator()
        about_action = app_menu.addAction(
            aw_icon("fa6s.circle-info", "#b8c8ce"), "Acerca de AuralWarden"
        )
        about_action.triggered.connect(self.open_about)
        menu_button.setMenu(app_menu)
        header.addWidget(menu_button)
        return header

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(5, 0, 5, 0)
        self.save_button = QPushButton("Guardar transcripción")
        self.save_button.setIcon(aw_icon("fa6s.floppy-disk", "#b8c8ce"))
        self.save_button.setProperty("flat", True)
        self.save_button.clicked.connect(self.save_transcript)
        self.transcripts_button = QPushButton("Transcripciones")
        self.transcripts_button.setIcon(aw_icon("fa6s.book-open", "#b8c8ce"))
        self.transcripts_button.setProperty("flat", True)
        self.transcripts_button.setToolTip(
            "Leer transcripciones anteriores dentro de AuralWarden"
        )
        self.transcripts_button.clicked.connect(self.open_transcript_library)
        self.speakers_button = QPushButton("Hablantes")
        self.speakers_button.setIcon(aw_icon("fa6s.user-group", "#b8c8ce"))
        self.speakers_button.setProperty("flat", True)
        self.speakers_button.clicked.connect(self.open_speakers)
        self.files_button = QPushButton("Archivos")
        self.files_button.setIcon(aw_icon("fa6s.folder-open", "#b8c8ce"))
        self.files_button.setProperty("flat", True)
        self.files_button.setToolTip("Abrir clips y transcripciones de la sesión")
        files_menu = QMenu(self.files_button)
        video_action = files_menu.addAction(
            aw_icon("fa6s.video", "#b8c8ce"), "Clips de vídeo"
        )
        video_action.triggered.connect(lambda: self._open_output_folder("video"))
        audio_action = files_menu.addAction(
            aw_icon("fa6s.wave-square", "#b8c8ce"), "Clips de audio"
        )
        audio_action.triggered.connect(lambda: self._open_output_folder("audio"))
        recordings_action = files_menu.addAction(
            aw_icon("fa6s.record-vinyl", "#b8c8ce"), "Grabaciones completas"
        )
        recordings_action.triggered.connect(
            lambda: self._open_output_folder("recordings")
        )
        transcript_action = files_menu.addAction(
            aw_icon("fa6s.file-lines", "#b8c8ce"), "Transcripciones"
        )
        transcript_action.triggered.connect(
            lambda: self._open_output_folder("transcripts")
        )
        self.files_button.setMenu(files_menu)
        self.presets_button = QPushButton("Presets")
        self.presets_button.setIcon(aw_icon("fa6s.sliders", "#b8c8ce"))
        self.presets_button.setProperty("flat", True)
        self.presets_button.setToolTip("Guardar o aplicar grupos de configuración")
        self.presets_button.clicked.connect(self.open_presets)
        self.history_button = QPushButton("Historial")
        self.history_button.setIcon(aw_icon("fa6s.clock-rotate-left", "#b8c8ce"))
        self.history_button.setProperty("flat", True)
        self.history_button.setToolTip("Buscar alertas anteriores y abrir su evidencia")
        self.history_button.clicked.connect(self.open_alert_history)
        self.last_event_label = QLabel(self._last_match)
        self.last_event_label.setProperty("muted", True)
        self.clips_label = QLabel("0 clips")
        self.clips_label.setProperty("muted", True)
        privacy_icon = QLabel()
        privacy_icon.setPixmap(aw_icon("fa6s.shield-halved", "#27c69a").pixmap(15, 15))
        self.privacy_label = QLabel("Todo se procesa localmente en este equipo")
        self.privacy_label.setProperty("muted", True)
        self.version_label = QLabel(f"v{__version__} · Made by Yojemr")
        self.version_label.setProperty("muted", True)
        self.version_label.setToolTip("AuralWarden, creado por Yojemr")
        footer.addWidget(self.save_button)
        footer.addWidget(self.transcripts_button)
        footer.addWidget(self.speakers_button)
        footer.addWidget(self.files_button)
        footer.addWidget(self.presets_button)
        footer.addWidget(self.history_button)
        footer.addSpacing(12)
        footer.addWidget(self.last_event_label)
        footer.addWidget(self.clips_label)
        footer.addStretch()
        footer.addWidget(privacy_icon)
        footer.addWidget(self.privacy_label)
        footer.addSpacing(14)
        footer.addWidget(self.version_label)
        return footer

    def _apply_settings_to_controls(self) -> None:
        kind_index = self.source_kind.findData(self.settings.source_kind)
        self.source_kind.blockSignals(True)
        self.source_kind.setCurrentIndex(max(0, kind_index))
        self.source_kind.blockSignals(False)
        self.source_input.setText(self.settings.source_url)
        self._source_kind_changed()
        self.hotword_editor.set_speaker_profiles(self.speaker_profiles.names())
        self.hotword_editor.set_hotwords(self.settings.hotwords)
        self.quick_settings.pre_seconds.setValue(self.settings.clip_pre_seconds)
        self.quick_settings.post_seconds.setValue(self.settings.clip_post_seconds)
        self.quick_settings.save_full_audio.setChecked(self.settings.save_full_audio)
        self.quick_settings.save_full_video.setChecked(self.settings.save_full_video)
        self.quick_settings.use_youtube_captions.setChecked(
            self.settings.use_youtube_captions
        )
        self._update_caption_preview_visibility()
        self.quick_settings.save_event_clips.setChecked(self.settings.save_event_audio_clips)
        self.quick_settings.save_event_video_clips.setChecked(
            self.settings.save_event_video_clips
        )
        self.quick_settings.diarization.setChecked(self.settings.diarization_enabled)
        self.quick_settings.expected_speakers.setValue(
            self.settings.diarization_num_speakers
        )
        if self.settings.desktop_notifications and self.settings.sound_notifications:
            mode = "Sonido + Windows"
        elif self.settings.desktop_notifications:
            mode = "Solo Windows"
        elif self.settings.sound_notifications:
            mode = "Solo sonido"
        else:
            mode = "Silenciosa"
        self.quick_settings.notification_mode.setCurrentText(mode)
        sound_map = {
            "Default": "Alerta amable",
            "Asterisk": "Aviso",
            "Exclamation": "Discreta",
        }
        self.quick_settings.sound.setCurrentText(
            sound_map.get(self.settings.notification_sound, "Alerta amable")
        )
        if self.settings.source_kind == "url":
            fallback = fallback_source_info(self.settings.source_url)
            self.preview_panel.set_title(fallback.title, fallback.author)
        else:
            self._source_device_changed()
        preview_mode = (
            "sincronizada con la transcripción"
            if self.settings.preview_mode == "synced"
            else "con menor latencia"
        )
        self.preview_panel.preview_button.setToolTip(
            "Activar la vista "
            f"{preview_mode}. El monitoreo de audio continúa aunque permanezca apagada."
        )
        self.privacy_label.setToolTip(
            "El control para agentes está habilitado y limitado a este equipo."
            if self.settings.allow_local_control
            else "El control para agentes está desactivado."
        )

    def _collect_settings(self) -> AppSettings:
        self.settings.source_kind = str(self.source_kind.currentData() or "url")
        self.settings.source_url = self.source_input.text().strip()
        selected_device = str(self.source_device.currentData() or "")
        if self.settings.source_kind == "system_audio":
            self.settings.system_audio_device = selected_device
        elif self.settings.source_kind == "microphone":
            self.settings.microphone_device = selected_device
        self.settings.source_title = self._current_source_title
        self.settings.hotwords = self.hotword_editor.hotwords()
        self.settings.clip_pre_seconds = self.quick_settings.pre_seconds.value()
        self.settings.clip_post_seconds = self.quick_settings.post_seconds.value()
        self.settings.save_full_audio = self.quick_settings.save_full_audio.isChecked()
        self.settings.save_full_video = (
            self.quick_settings.save_full_video.isChecked()
            and self.settings.source_kind == "url"
            and self._source_supports_video()
        )
        self.settings.use_youtube_captions = (
            self.quick_settings.use_youtube_captions.isChecked()
            and self.settings.source_kind == "url"
            and is_youtube_source(self.settings.source_url)
        )
        self.settings.save_event_audio_clips = (
            self.quick_settings.save_event_clips.isChecked()
        )
        self.settings.save_event_video_clips = (
            self.quick_settings.save_event_video_clips.isChecked()
            and self.settings.source_kind == "url"
            and self._source_supports_video()
        )
        voice_filter_enabled = any(
            item.enabled and item.speaker_profile.strip()
            for item in self.settings.hotwords
        )
        self.settings.diarization_enabled = (
            self.quick_settings.diarization.isChecked() or voice_filter_enabled
        )
        if voice_filter_enabled:
            self.quick_settings.diarization.setChecked(True)
        self.settings.diarization_num_speakers = (
            self.quick_settings.expected_speakers.value()
        )
        mode = self.quick_settings.notification_mode.currentText()
        self.settings.desktop_notifications = mode in {
            "Sonido + Windows",
            "Solo Windows",
        }
        self.settings.sound_notifications = mode in {
            "Sonido + Windows",
            "Solo sonido",
        }
        sound_map = {
            "Alerta amable": "Default",
            "Aviso": "Asterisk",
            "Discreta": "Exclamation",
        }
        self.settings.notification_sound = sound_map.get(
            self.quick_settings.sound.currentText(), "Default"
        )
        return self.settings

    def _apply_clip_switches(self, *_: object) -> None:
        if not self.controller.running:
            return
        audio = self.quick_settings.save_event_clips.isChecked()
        video = self.quick_settings.save_event_video_clips.isChecked()
        self.controller.update_clip_preferences(audio, video)
        self.settings.save_event_audio_clips = audio
        self.settings.save_event_video_clips = video

    def _queue_hotword_update(self) -> None:
        self._hotword_update_timer.start()

    def _apply_hotword_changes(self) -> None:
        hotwords = self.hotword_editor.hotwords()
        self.settings.hotwords = hotwords
        self.controller.update_hotwords(hotwords)
        try:
            self.store.save(self.settings)
        except OSError:
            pass

    def _source_kind_changed(self, *_: object) -> None:
        kind = str(self.source_kind.currentData() or "url")
        is_url = kind == "url"
        self.source_input.setVisible(is_url)
        self.source_browse.setVisible(is_url)
        self.source_device.setVisible(not is_url)
        self.source_refresh.setVisible(not is_url)
        self.silent_button.setVisible(kind == "system_audio")
        self.preview_panel.preview_button.setEnabled(is_url)
        self.preview_panel.open_button.setEnabled(is_url)
        self.quick_settings.save_event_video_clips.setEnabled(is_url)
        self.quick_settings.save_full_video.setEnabled(is_url)
        self.quick_settings.use_youtube_captions.setEnabled(
            is_url and is_youtube_source(self.source_input.text().strip())
        )
        if not is_url:
            self.quick_settings.save_event_video_clips.setChecked(False)
            self.quick_settings.save_full_video.setChecked(False)
            self.quick_settings.use_youtube_captions.setChecked(False)
            self.preview.stop()
            self.preview_panel.set_preview_active(False)
            self._refresh_audio_devices()
        else:
            self.source_icon.setPixmap(aw_icon("fa6s.link", "#aebdc4").pixmap(20, 20))
            self._update_url_capabilities()
            self._request_source_title()
        self._update_caption_preview_visibility()

    def _refresh_audio_devices(self) -> None:
        kind = str(self.source_kind.currentData() or "url")
        if kind == "url":
            return
        preferred = (
            self.settings.system_audio_device
            if kind == "system_audio"
            else self.settings.microphone_device
        )
        current = str(self.source_device.currentData() or preferred)
        self.source_device.blockSignals(True)
        self.source_device.clear()
        try:
            devices = list_windows_audio_devices(kind)
        except WindowsAudioError as exc:
            self.source_device.addItem("No disponible", "")
            self.source_device.setToolTip(str(exc))
            devices = []
        for device in devices:
            label = f"{device.name} · Predeterminado" if device.is_default else device.name
            self.source_device.addItem(label, device.name)
        selected = self.source_device.findData(current)
        if selected < 0:
            selected = next(
                (
                    index
                    for index, device in enumerate(devices)
                    if device.is_default
                ),
                0,
            )
        self.source_device.setCurrentIndex(selected if self.source_device.count() else -1)
        self.source_device.blockSignals(False)
        self._source_device_changed()

    def _source_device_changed(self, *_: object) -> None:
        kind = str(self.source_kind.currentData() or "url")
        name = str(self.source_device.currentData() or "")
        if kind == "system_audio":
            self.source_icon.setPixmap(
                aw_icon("fa6s.desktop", "#27c69a").pixmap(20, 20)
            )
            self._current_source_title = "Audio del sistema"
            self.preview_panel.set_title("Audio del sistema", name.removesuffix(" [Loopback]"))
        elif kind == "microphone":
            self.source_icon.setPixmap(
                aw_icon("fa6s.microphone", "#18baf2").pixmap(20, 20)
            )
            self._current_source_title = "Entrada de micrófono"
            self.preview_panel.set_title("Entrada de micrófono", name)

    def _source_supports_video(self) -> bool:
        suffix = Path(urlparse(self.source_input.text().strip()).path).suffix.casefold()
        return suffix not in {".aac", ".flac", ".m3u", ".m4a", ".mp3", ".ogg", ".opus", ".pls", ".wav"}

    def _update_url_capabilities(self) -> None:
        enabled = self._source_supports_video()
        self.quick_settings.save_event_video_clips.setEnabled(enabled)
        self.quick_settings.save_full_video.setEnabled(enabled)
        youtube = is_youtube_source(self.source_input.text().strip())
        self.quick_settings.use_youtube_captions.setEnabled(youtube)
        if not youtube:
            self.quick_settings.use_youtube_captions.setChecked(False)
            self.quick_settings.use_youtube_captions.setToolTip(
                "La fuente auxiliar de subtítulos está disponible únicamente para YouTube"
            )
        else:
            self.quick_settings.use_youtube_captions.setToolTip(
                "Usar subtítulos de YouTube como ayuda independiente para detectar hotwords"
            )
        if not enabled:
            self.quick_settings.save_event_video_clips.setChecked(False)
            self.quick_settings.save_full_video.setChecked(False)
            self.quick_settings.save_event_video_clips.setToolTip(
                "Esta dirección parece contener solo audio; AuralWarden guardará clips WAV."
            )
        else:
            self.quick_settings.save_event_video_clips.setToolTip(
                "Crear un MP4 con vídeo y audio cuando se detecte una hotword"
            )
            self.quick_settings.save_full_video.setToolTip(
                "Guardar todo el vídeo del directo. Puede ocupar varios gigabytes"
            )
        self._update_caption_preview_visibility()

    def _update_caption_preview_visibility(self, *_: object) -> None:
        if not hasattr(self, "caption_preview") or not hasattr(
            self, "quick_settings"
        ):
            return
        visible = (
            str(self.source_kind.currentData() or "url") == "url"
            and is_youtube_source(self.source_input.text().strip())
            and self.quick_settings.use_youtube_captions.isChecked()
        )
        self.caption_preview.set_option_visible(visible)

    def start_monitoring(self, *, interactive: bool = True) -> bool:
        if self.controller.running:
            return False
        if self.controller.transcript_dirty:
            if not interactive:
                raise RuntimeError(
                    "Hay una transcripción sin guardar. Guárdala o descártala desde la aplicación antes de iniciar otra sesión."
                )
            if not self._resolve_unsaved_transcript("Antes de iniciar una nueva sesión"):
                return False
        settings = self._collect_settings()
        if settings.source_kind == "url" and not settings.source_url:
            message = "Pega un enlace o elige un archivo."
            if interactive:
                QMessageBox.warning(self, "Falta la fuente", message)
                self.source_input.setFocus()
                return False
            raise ValueError(message)
        if settings.source_kind in {"system_audio", "microphone"}:
            selected_device = (
                settings.system_audio_device
                if settings.source_kind == "system_audio"
                else settings.microphone_device
            )
            if not selected_device:
                message = "Selecciona un dispositivo de audio disponible."
                if interactive:
                    QMessageBox.warning(self, "Falta el dispositivo", message)
                    return False
                raise ValueError(message)
        # Generic labels such as "Speaker 2" are assigned afresh by every
        # session. Manual display names must not follow that number into a new
        # recording; persistent identity is handled only by voice profiles.
        settings.speaker_names.clear()
        try:
            self.store.save(settings)
            self.transcript.clear()
            self.activity.clear()
            self._speakers.clear()
            self._speaker_displays.clear()
            self._clip_count = 0
            self._clip_events.clear()
            self._last_audio_level = 0.0
            self.resources.update_audio_level(0.0)
            self.clips_label.setText("0 clips")
            self.last_event_label.setText("Sin coincidencias")
            self.controller.start(settings)
        except FileNotFoundError as exc:
            self._set_state(SessionState.FAILED)
            if not interactive:
                raise RuntimeError(str(exc)) from exc
            QMessageBox.warning(self, "Preparación pendiente", str(exc))
            if "modelo" in str(exc).casefold():
                self.open_model_setup()
            return False
        except Exception as exc:
            self._set_state(SessionState.FAILED)
            if interactive:
                QMessageBox.critical(self, "No fue posible iniciar", str(exc))
                return False
            raise RuntimeError(str(exc)) from exc
        self._started_monotonic = time.monotonic()
        self._stopped_elapsed = None
        source_labels = {
            "system_audio": "Audio del sistema",
            "microphone": "Micrófono",
        }
        self.resources.source_label.setText(
            source_labels.get(
                settings.source_kind,
                "Demostración local"
                if settings.source_url.startswith("demo://")
                else "Enlace / archivo",
            )
        )
        demo = settings.source_kind == "url" and settings.source_url.startswith("demo://")
        self.caption_preview.set_option_visible(
            settings.use_youtube_captions
            and settings.source_kind == "url"
            and is_youtube_source(settings.source_url)
        )
        if self.caption_preview.isVisible():
            self.caption_preview.begin()
        self.preview.stop()
        self.preview_panel.set_monitoring(True, demo=demo)
        if settings.source_kind != "url":
            self.preview_panel.preview_button.setEnabled(False)
            self.preview_panel.open_button.setEnabled(False)
        if settings.source_kind == "url":
            self._request_source_title()
        else:
            self._source_device_changed()
        self._set_state(SessionState.STARTING)
        return True

    def stop_monitoring(self) -> None:
        self._restore_silent_audio("La salida se restauró al detener el monitoreo.")
        self.controller.stop()
        self.preview.stop()
        self.preview_panel.set_preview_active(False)
        self._set_state(SessionState.STOPPING)

    def _handle_event(self, event: EngineEvent) -> None:
        if event.kind == EventKind.STATE:
            try:
                self._set_state(SessionState(str(event.payload.get("state"))))
            except ValueError:
                return
        elif event.kind == EventKind.TRANSCRIPT:
            self.transcript.append_entry(event.payload)
            speaker = str(event.payload.get("speaker_id") or "")
            speaker_key = str(event.payload.get("speaker_key") or speaker)
            if speaker:
                self._speakers.add(speaker)
                self._speaker_displays[speaker_key] = speaker
        elif event.kind == EventKind.RESOURCE:
            self.resources.update_snapshot(event.payload)
        elif event.kind == EventKind.HOTWORD:
            if bool(event.payload.get("created", True)):
                self.activity.add_detection(event.payload)
                try:
                    self.alert_history.add_detection(
                        event.payload,
                        source_title=self._current_source_title,
                        session_path=self.controller.session_path,
                    )
                except OSError:
                    pass
                phrase = str(event.payload.get("phrase") or "Coincidencia")
                score = float(event.payload.get("score") or 0.0)
                speaker = str(event.payload.get("speaker_id") or "").strip()
                self._last_match = f"Última alerta: {phrase} · {score:.0f} %"
                self.last_event_label.setText(self._last_match)
                self._reveal_audio_for_alert(phrase)
                self._notify(phrase, score, speaker)
                self._update_tray_menu()
        elif event.kind == EventKind.CLIP:
            self.activity.mark_clip(event.payload)
            event_id = str(event.payload.get("event_id") or "")
            try:
                self.alert_history.attach_clip(
                    event_id,
                    str(event.payload.get("path") or ""),
                    str(event.payload.get("media_type") or "audio/wav"),
                )
            except OSError:
                pass
            self._clip_events.add(event_id)
            self._clip_count = len(self._clip_events)
            unit = "clip" if self._clip_count == 1 else "clips"
            self.clips_label.setText(f"{self._clip_count} {unit}")
        elif event.kind == EventKind.INFO:
            if event.payload.get("phase") == "audio_level":
                self._last_audio_level = float(event.payload.get("level") or 0.0)
                self.resources.update_audio_level(self._last_audio_level)
                return
            code = str(event.payload.get("code") or "")
            if code == "capture_backlog":
                queued = float(event.payload.get("queued_seconds") or 0.0)
                dropped = float(event.payload.get("dropped_seconds") or 0.0)
                self._status_detail = f"Transcripción retrasada {queued:.0f} s respecto a la captura."
                if dropped > 0:
                    self._status_detail += f" Se omitieron {dropped:.0f} s por saturación."
                self.status_label.setText(f"Monitoreo · retraso {queued:.0f} s")
                self.status_label.setToolTip(self._status_detail)
                self._write_runtime_status()
                return
            if code == "caption_cue":
                self.caption_preview.add_cue(
                    str(event.payload.get("text") or ""),
                    float(event.payload.get("elapsed_seconds") or 0.0),
                )
                return
            if code == "caption_track_ready":
                self.caption_preview.set_track(
                    str(event.payload.get("language") or ""),
                    bool(event.payload.get("automatic", False)),
                )
            elif code == "caption_track_waiting":
                self.caption_preview.set_waiting(
                    str(event.payload.get("message") or ""),
                    float(event.payload.get("delay_seconds") or 0.0),
                )
            elif code == "caption_track_retrying":
                self.caption_preview.set_retrying(
                    str(event.payload.get("message") or ""),
                    float(event.payload.get("delay_seconds") or 0.0),
                )
            elif code == "caption_monitor_unavailable":
                self.caption_preview.set_unavailable(
                    str(event.payload.get("message") or ""),
                    retrying=bool(event.payload.get("retrying", False)),
                )
            if code == "video_clip_failed":
                self.activity.mark_clip_failed(event.payload)
                self.status_label.setToolTip(str(event.payload.get("message") or ""))
            elif code in {
                "caption_monitor_started",
                "caption_track_waiting",
                "caption_track_retrying",
                "caption_monitor_unavailable",
                "full_video_saved",
                "full_video_failed",
                "video_recovery_available",
                "video_cleanup_deferred",
            }:
                message = str(event.payload.get("message") or "")
                self._status_detail = message
                self.status_label.setToolTip(message)
            phase = str(event.payload.get("phase") or "")
            if phase in {"waiting", "reconnecting", "connected", "ended"}:
                attempt = int(event.payload.get("attempt") or 0)
                delay = int(float(event.payload.get("delay_seconds") or 0))
                message = str(event.payload.get("message") or "")
                if phase == "waiting":
                    self._status_detail = (
                        f"El directo todavía no entrega audio. Intento {attempt}; "
                        f"nuevo intento en {delay} s. {message}"
                    )
                elif phase == "reconnecting":
                    self._status_detail = (
                        f"La transmisión se interrumpió. Intento {attempt}; "
                        f"nuevo intento en {delay} s. {message}"
                    )
                elif phase == "connected":
                    self._status_detail = message or "Conexión activa."
                else:
                    self._status_detail = message or "El directo finalizó."
                self.status_label.setToolTip(self._status_detail)
                self._write_runtime_status()
        elif event.kind == EventKind.ERROR:
            message = str(event.payload.get("message") or "Error desconocido")
            self._status_detail = message
            self.status_label.setToolTip(message)
            self._restore_silent_audio("La salida se restauró después de un error.")
            QMessageBox.critical(self, "AuralWarden se detuvo", message)

    def _set_state(self, state: SessionState) -> None:
        self._current_state = state
        labels = {
            SessionState.IDLE: "En espera",
            SessionState.STARTING: "Preparando monitor",
            SessionState.RUNNING: "Monitoreo activo",
            SessionState.WAITING: "Esperando directo",
            SessionState.RECONNECTING: "Reconectando",
            SessionState.STOPPING: "Deteniendo",
            SessionState.STOPPED: "Sesión detenida",
            SessionState.FAILED: "Requiere atención",
        }
        colors = {
            SessionState.RUNNING: "#27c69a",
            SessionState.STARTING: "#f0ac24",
            SessionState.WAITING: "#f0ac24",
            SessionState.RECONNECTING: "#f0ac24",
            SessionState.STOPPING: "#f0ac24",
            SessionState.FAILED: "#ef616c",
        }
        self.status_label.setText(labels[state])
        self.status_dot.setStyleSheet(
            f"background:{colors.get(state, '#657680')};border-radius:4px;"
        )
        running = state in {
            SessionState.STARTING,
            SessionState.RUNNING,
            SessionState.WAITING,
            SessionState.RECONNECTING,
            SessionState.STOPPING,
        }
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(
            state
            in {
                SessionState.STARTING,
                SessionState.RUNNING,
                SessionState.WAITING,
                SessionState.RECONNECTING,
            }
        )
        self.source_input.setEnabled(not running)
        self.source_kind.setEnabled(not running)
        self.source_device.setEnabled(not running)
        self.source_browse.setEnabled(not running)
        self.source_refresh.setEnabled(not running)
        panel = self.quick_settings
        for field in (panel.save_full_audio, panel.save_full_video, panel.diarization,
                      panel.expected_speakers, panel.use_youtube_captions,
                      panel.pre_seconds, panel.post_seconds):
            if field.property("sessionTooltip") is None:
                field.setProperty("sessionTooltip", field.toolTip())
            field.setEnabled(not running)
            field.setToolTip(
                "Se configura antes de iniciar el monitoreo."
                if running else str(field.property("sessionTooltip") or "")
            )
        engine = getattr(self.controller, "engine", None)
        video_ready = bool(getattr(engine, "video_capture_available", False))
        panel.save_event_video_clips.setEnabled(
            video_ready if running else self.settings.source_kind == "url" and self._source_supports_video()
        )
        panel.save_event_video_clips.setToolTip(
            "Pausar o reanudar clips nuevos. Los pendientes terminan y el búfer temporal continúa."
            if running and video_ready else
            "La sesión empezó sin vídeo. Actívalo antes de iniciar un nuevo monitoreo."
            if running else "Crear un MP4 con vídeo y audio cuando se detecte una hotword"
        )
        if not running:
            panel.save_full_video.setEnabled(self.settings.source_kind == "url" and self._source_supports_video())
            panel.use_youtube_captions.setEnabled(
                self.settings.source_kind == "url" and is_youtube_source(self.source_input.text())
            )
        self.silent_button.setEnabled(
            running
            and self.settings.source_kind == "system_audio"
            and state in {SessionState.STARTING, SessionState.RUNNING}
        )
        if state in {SessionState.STOPPED, SessionState.FAILED}:
            self._restore_silent_audio("La salida de audio fue restaurada.")
            self._last_audio_level = 0.0
            self.resources.update_audio_level(0.0)
            if self._started_monotonic is not None:
                self._stopped_elapsed = int(
                    max(0.0, time.monotonic() - self._started_monotonic)
                )
            self.preview.stop()
            self.preview_panel.set_monitoring(False)
            self.caption_preview.finish()
            session_path = self.controller.session_path
            if session_path is not None:
                self.session_label.setText(f"Sesión: {session_path.name}")
                self.session_label.setToolTip(str(session_path))
        elif state == SessionState.RUNNING:
            self.session_label.setText("Sesión local activa")
        elif state == SessionState.WAITING:
            self.session_label.setText("Esperando que comience el directo")
        elif state == SessionState.RECONNECTING:
            self.session_label.setText("Recuperando la conexión")
        self._update_tray_menu()
        self._write_runtime_status()

    def _update_elapsed(self) -> None:
        if self._stopped_elapsed is not None:
            total = self._stopped_elapsed
        elif self._started_monotonic is None:
            total = 0
        else:
            total = int(max(0.0, time.monotonic() - self._started_monotonic))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.preview_panel.time_label.setText(text)
        self.resources.elapsed_label.setText(text)
        if self._current_state not in {
            SessionState.STARTING,
            SessionState.RUNNING,
            SessionState.WAITING,
            SessionState.RECONNECTING,
            SessionState.STOPPING,
        }:
            return
        self.tray.setToolTip(f"AuralWarden · {self.status_label.text()} · {text}")

    def preview_panel_set_frame(self, frame: bytes) -> None:
        self.preview_panel.set_frame(frame)

    def toggle_preview(self) -> None:
        if (
            not self.controller.running
            or self.settings.source_kind != "url"
            or self.settings.source_url.startswith("demo://")
        ):
            return
        if self.preview.active:
            self.preview.stop()
            self.preview_panel.set_preview_active(False)
            return
        self.preview_panel.set_preview_active(True)
        self.preview.start(
            self.settings.source_url,
            synced=self.settings.preview_mode == "synced",
            delay_seconds=self.settings.transcription_window_seconds,
        )

    def _preview_status(self, status: str) -> None:
        self.preview_panel.mode_label.setText(status)

    def _preview_error(self, message: str) -> None:
        self.preview_panel.set_preview_active(False)
        self.preview_panel.mode_label.setText("Preview no disponible")
        self.preview_panel.mode_label.setToolTip(message)

    def _source_info_ready(self, source: str, info: SourceInfo) -> None:
        if source != self.source_input.text().strip():
            return
        self.preview_panel.set_title(info.title, info.author)
        self._current_source_title = info.title

    def _request_source_title(self) -> None:
        if str(self.source_kind.currentData() or "url") != "url":
            self._source_device_changed()
            return
        self._update_url_capabilities()
        source = self.source_input.text().strip()
        fallback = fallback_source_info(source)
        self.preview_panel.set_title(fallback.title, fallback.author)
        self._current_source_title = fallback.title
        if source:
            self.source_info.request(source)

    def _toggle_silent_monitoring(self) -> None:
        if self.silent_audio.active:
            self._restore_silent_audio("La salida de audio fue restaurada manualmente.")
            return
        if not self.controller.running or self.settings.source_kind != "system_audio":
            return
        if self._last_audio_level <= 0.0001:
            QMessageBox.warning(
                self,
                "Todavía no hay audio",
                "AuralWarden aún no detecta sonido en esta salida. Reproduce la reunión o transmisión y comprueba que el medidor Audio se active antes de silenciarla.",
            )
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Activar monitorización silenciosa")
        box.setText("AuralWarden silenciará toda la salida seleccionada.")
        box.setInformativeText(
            "Seguirá analizando el audio internamente. Al detectar cualquier hotword, "
            "restaurará el dispositivo, lo dejará encendido y no volverá a silenciarlo "
            "automáticamente. También restaurará el audio al detenerse, cerrarse o fallar.\n\n"
            "Este cambio afecta el sonido de todas las aplicaciones que usan esa salida."
        )
        activate = box.addButton("Silenciar y continuar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not activate:
            return
        device_name = str(self.source_device.currentData() or "")
        try:
            original = self.silent_audio.activate(device_name)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "No se pudo silenciar la salida",
                str(exc),
            )
            return
        self._status_detail = (
            f"Monitorización silenciosa activa en {original.device_name}. "
            "Una hotword restaurará el audio permanentemente."
        )
        self.status_label.setToolTip(self._status_detail)
        self._update_silent_controls()

    def _restore_silent_audio(self, detail: str = "") -> None:
        if not self.silent_audio.active:
            return
        try:
            restored = self.silent_audio.restore_original()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "No se pudo restaurar el audio",
                f"Usa el control de volumen de Windows para reactivar la salida.\n\n{exc}",
            )
            return
        if restored and detail:
            self._status_detail = detail
            self.status_label.setToolTip(detail)
        self._update_silent_controls()

    def _reveal_audio_for_alert(self, phrase: str) -> None:
        if not self.silent_audio.active:
            return
        try:
            revealed = self.silent_audio.reveal_for_alert()
        except Exception as exc:
            self._status_detail = f"No se pudo restaurar automáticamente el audio: {exc}"
            self.status_label.setToolTip(self._status_detail)
            return
        if not revealed:
            return
        self._status_detail = (
            f"La hotword '{phrase}' restauró la salida. Permanecerá encendida."
        )
        self.status_label.setToolTip(self._status_detail)
        self._update_silent_controls()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                "Audio restaurado por una alerta",
                f"Se detectó “{phrase}”. La salida permanecerá encendida.",
                QSystemTrayIcon.MessageIcon.Information,
                7_000,
            )

    def _check_silent_audio_state(self) -> None:
        if self._silent_recovery_error and self._silent_recovery_attempts < 5:
            self._silent_recovery_attempts += 1
            try:
                self.silent_audio.recover_interrupted()
            except Exception as exc:
                self._silent_recovery_error = str(exc)
            else:
                self._silent_recovery_error = ""
                self._status_detail = "La salida de audio fue restaurada."
                self.status_label.setToolTip(self._status_detail)
            self._update_silent_controls()
            return
        if not self.silent_audio.active:
            return
        try:
            changed = self.silent_audio.abandon_if_unmuted()
        except Exception:
            return
        if changed:
            self._status_detail = (
                "La salida se activó externamente; AuralWarden dejó de controlar su silencio."
            )
            self.status_label.setToolTip(self._status_detail)
            self._update_silent_controls()

    def _update_silent_controls(self) -> None:
        active = self.silent_audio.active
        self.silent_button.setText("Restaurar audio" if active else "Silenciar salida")
        self.silent_button.setIcon(
            aw_icon("fa6s.volume-high" if active else "fa6s.volume-xmark", "#d8e0e4")
        )
        if hasattr(self, "tray_restore_audio"):
            self.tray_restore_audio.setVisible(active)
            self.tray_restore_audio.setEnabled(active)
        self._write_runtime_status()

    def _notify(self, phrase: str, score: float, speaker: str = "") -> None:
        if self._muted:
            return
        detail = f"{phrase} · {score:.0f} %"
        if speaker:
            detail += f" · {speaker}"
        self._emit_notification(
            "AuralWarden detectó una coincidencia",
            detail,
            desktop=self.settings.desktop_notifications,
            sound=self.settings.sound_notifications,
            sound_name=self.settings.notification_sound,
        )

    def _emit_notification(
        self,
        title: str,
        message: str,
        *,
        desktop: bool,
        sound: bool,
        sound_name: str,
    ) -> None:
        if desktop and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5_000,
            )
        if sound:
            self._play_notification_sound(sound_name)

    @staticmethod
    def _sound_key(display_name: str) -> str:
        return {
            "Alerta amable": "Default",
            "Aviso": "Asterisk",
            "Discreta": "Exclamation",
        }.get(display_name, "Default")

    @staticmethod
    def _play_notification_sound(sound_name: str) -> None:
        if sys.platform == "win32":
            try:
                import winsound

                sound_files = {
                    "Default": "notification-friendly.wav",
                    "Asterisk": "notification-notice.wav",
                    "Exclamation": "notification-discreet.wav",
                }
                sound_path = asset_path(sound_files.get(sound_name, "notification-friendly.wav"))
                if sound_path.is_file():
                    winsound.PlaySound(
                        str(sound_path),
                        winsound.SND_FILENAME
                        | winsound.SND_ASYNC
                        | winsound.SND_NODEFAULT,
                    )
                    return
            except (ImportError, RuntimeError):
                pass
        QApplication.beep()

    def test_notification_sound(self) -> None:
        self._play_notification_sound(
            self._sound_key(self.quick_settings.sound.currentText())
        )

    def test_notification(self) -> None:
        mode = self.quick_settings.notification_mode.currentText()
        desktop = mode in {"Sonido + Windows", "Solo Windows"}
        sound = mode in {"Sonido + Windows", "Solo sonido"}
        if not desktop and not sound:
            QMessageBox.information(
                self,
                "Notificación silenciosa",
                "El modo seleccionado no produce sonido ni aviso de Windows.",
            )
            return
        self._emit_notification(
            "Prueba de AuralWarden",
            "Las notificaciones están configuradas correctamente.",
            desktop=desktop,
            sound=sound,
            sound_name=self._sound_key(self.quick_settings.sound.currentText()),
        )

    def save_transcript(self) -> bool:
        if not self.controller.transcript_entries:
            QMessageBox.information(self, "Sin transcripción", "Todavía no hay texto para guardar.")
            return False
        destination = self.controller.transcripts_path or transcripts_dir()
        destination.mkdir(parents=True, exist_ok=True)
        default = destination / f"{date_time_label(datetime.now())} - Transcripcion.txt"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar transcripción",
            str(default),
            "Texto (*.txt)",
        )
        if not selected:
            return False
        try:
            self.controller.export_transcript(Path(selected))
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return False
        self.status_label.setToolTip(f"Transcripción guardada en {selected}")
        return True

    def _open_output_folder(self, category: str) -> None:
        current = {
            "video": self.controller.video_clips_path,
            "audio": self.controller.audio_clips_path,
            "recordings": self.controller.recordings_path,
            "transcripts": self.controller.transcripts_path,
        }.get(category)
        target = current or self._latest_output_folder(category)
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

    @staticmethod
    def _latest_output_folder(category: str) -> Path:
        root = sessions_dir()
        try:
            sessions = sorted(
                (path for path in root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
        except OSError:
            sessions = []
        if not sessions:
            return root
        relative = {
            "video": Path("clips") / "video",
            "audio": Path("clips") / "audio",
            "recordings": Path("recordings"),
            "transcripts": Path("transcripts"),
        }.get(category, Path())
        return sessions[0] / relative

    def open_preferences(self) -> None:
        was_enabled = self.settings.allow_local_control
        dialog = PreferencesDialog(self.settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        dialog.apply_to(self.settings)
        if self.settings.allow_local_control and not was_enabled:
            answer = QMessageBox.warning(
                self,
                "Habilitar control local",
                "Esta opción permite que otro programa o agente ejecutado en tu misma sesión de Windows consulte el estado y partes de la transcripción, cambie el enlace y las hotwords, e inicie o detenga AuralWarden.\n\n"
                "No abre puertos de red ni comparte claves de API. Cada orden exige una credencial aleatoria propia de esta carpeta y queda registrada sin argumentos ni texto. ¿Deseas habilitarla?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.settings.allow_local_control = False
            else:
                self.local_control_credentials.rotate()
        elif was_enabled and not self.settings.allow_local_control:
            self.local_control_credentials.revoke()
        elif self.settings.allow_local_control:
            self.local_control_credentials.ensure()
        self.store.save(self._collect_settings())
        self._apply_settings_to_controls()
        self._apply_interface_scale()

    def open_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Acerca de AuralWarden")
        box.setIconPixmap(QPixmap(str(asset_path("app-icon.png"))).scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        box.setText(f"AuralWarden {__version__}\nCreado por Yojemr")
        box.setInformativeText(
            "Software libre bajo GNU GPL versión 3 exclusivamente. Puedes copiarlo y modificarlo "
            "bajo esos términos. Se proporciona SIN GARANTÍA.\n\n"
            "Los componentes, modelos, iconos y herramientas de terceros conservan sus propias licencias. "
            "Consulta LICENSE, NOTICE y docs/THIRD_PARTY_NOTICES.md incluidos en la carpeta de AuralWarden."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def open_presets(self) -> None:
        if self.controller.running:
            QMessageBox.information(
                self,
                "Preset para la siguiente sesión",
                "Detén el monitoreo antes de aplicar un preset. Así el motor, los búferes y la diarización cambian juntos sin perder audio.",
            )
            return
        current = self._collect_settings()
        dialog = PresetDialog(self.presets, current, self)
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.selected_name:
            return
        try:
            self.settings = self.presets.apply(dialog.selected_name, current)
            self.store.save(self.settings)
        except (KeyError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo aplicar", str(exc))
            return
        self._apply_settings_to_controls()
        self._apply_interface_scale()
        self._status_detail = f"Preset aplicado: {dialog.selected_name}."
        self.status_label.setToolTip(self._status_detail)

    def open_alert_history(self) -> None:
        AlertHistoryDialog(self.alert_history, self).exec()

    def open_transcript_library(self) -> None:
        roots = [sessions_dir(), transcripts_dir()]
        if portable_mode():
            for previous in find_previous_portable_installations(application_root()):
                roots.extend(
                    [previous / "data" / "sessions", previous / "data" / "transcripts"]
                )
        TranscriptLibraryDialog(roots, self).exec()

    @staticmethod
    def _open_evidence(path: str) -> None:
        target = Path(path).expanduser()
        if target.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

    def _apply_interface_scale(self) -> None:
        scale = max(90, min(125, int(self.settings.interface_scale_percent)))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(scaled_stylesheet(scale))
        factor = scale / 100.0
        self.setMinimumSize(round(1080 * factor), round(700 * factor))
        self.privacy_label.setVisible(self.width() >= round(1280 * factor))

    def open_speakers(self) -> None:
        speakers = sorted(
            self._speaker_displays.items(), key=lambda item: item[1].casefold()
        )
        saved_profile_names = self.speaker_profiles.names()
        if not speakers and not saved_profile_names:
            QMessageBox.information(
                self,
                "Sin hablantes todavía",
                "Los hablantes aparecerán después de iniciar una transcripción con diarización. "
                "Luego podrás asignar nombres y guardar perfiles de voz voluntarios.",
            )
            return
        enrollable = {
            speaker_key
            for speaker_key, _ in speakers
            if self.controller.speaker_embedding(speaker_key) is not None
        }
        dialog = SpeakerNamesDialog(
            speakers,
            self.settings.speaker_names,
            enrollable,
            saved_profile_names,
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.speaker_profiles.delete(dialog.profile_deletions())
        saved_profiles: list[str] = []
        unavailable_profiles: list[str] = []
        for speaker_key, profile_name in dialog.profile_requests().items():
            embedding = self.controller.speaker_embedding(speaker_key)
            if embedding is None:
                unavailable_profiles.append(profile_name)
                continue
            self.speaker_profiles.save_embedding(profile_name, embedding)
            saved_profiles.append(profile_name)
        mapping = dialog.mapping()
        for speaker_key, display_name in mapping.items():
            current_display = self._speaker_displays.get(speaker_key, speaker_key)
            self.controller.rename_speaker(speaker_key, display_name)
            self._speakers.discard(current_display)
            self._speakers.add(display_name)
            self._speaker_displays[speaker_key] = display_name
        self.settings.speaker_names.update(mapping)
        self.store.save(self.settings)
        self.hotword_editor.set_speaker_profiles(self.speaker_profiles.names())
        entries = self.controller.transcript_entries
        if entries:
            self.transcript.clear()
            for entry in entries:
                self.transcript.append_entry(asdict(entry))
        if saved_profiles:
            self.quick_settings.diarization.setChecked(True)
            QMessageBox.information(
                self,
                "Perfiles de voz guardados",
                "AuralWarden recordará localmente: "
                + ", ".join(saved_profiles)
                + ". Ahora puedes elegir esos nombres en la columna Hablante de cada hotword.",
            )
        elif unavailable_profiles:
            QMessageBox.warning(
                self,
                "Muestra insuficiente",
                "No fue posible crear: " + ", ".join(unavailable_profiles) + ".",
            )

    def open_source(self) -> None:
        if self.settings.source_kind != "url":
            return
        source = self.source_input.text().strip()
        if not source or source.startswith("demo://"):
            return
        path = Path(source).expanduser()
        url = QUrl.fromLocalFile(str(path.resolve())) if path.exists() else QUrl(source)
        QDesktopServices.openUrl(url)

    def _browse_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar audio o vídeo",
            "",
            "Medios (*.mp4 *.mkv *.webm *.mov *.mp3 *.wav *.m4a *.aac);;Todos (*.*)",
        )
        if selected:
            self.source_input.setText(selected)
            self._request_source_title()

    def _create_tray(self) -> None:
        self.tray = QSystemTrayIcon(QIcon(str(asset_path("app-icon.png"))), self)
        self.tray.activated.connect(self._tray_activated)
        self.tray_menu = QMenu(self)
        self.tray_status = self.tray_menu.addAction("En espera")
        self.tray_status.setEnabled(False)
        self.tray_last = self.tray_menu.addAction(self._last_match)
        self.tray_last.setEnabled(False)
        self.tray_menu.addSeparator()
        open_action = self.tray_menu.addAction(aw_icon("fa6s.window-restore"), "Abrir AuralWarden")
        open_action.triggered.connect(self._restore_window)
        self.tray_mute = self.tray_menu.addAction(aw_icon("fa6s.volume-high"), "Silenciar alertas")
        self.tray_mute.triggered.connect(self._toggle_mute)
        self.tray_restore_audio = self.tray_menu.addAction(
            aw_icon("fa6s.volume-high", "#27c69a"), "Restaurar audio de Windows"
        )
        self.tray_restore_audio.triggered.connect(
            lambda: self._restore_silent_audio("La salida fue restaurada desde la bandeja.")
        )
        self.tray_restore_audio.setVisible(False)
        self.tray_stop = self.tray_menu.addAction(aw_icon("fa6s.stop"), "Detener monitoreo")
        self.tray_stop.triggered.connect(self.stop_monitoring)
        self.tray_menu.addSeparator()
        exit_action = self.tray_menu.addAction(aw_icon("fa6s.power-off"), "Salir")
        exit_action.triggered.connect(self._request_quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()
        self._update_tray_menu()

    def _update_tray_menu(self) -> None:
        if not hasattr(self, "tray_status"):
            return
        self.tray_status.setText(self.status_label.text())
        self.tray_last.setText(self._last_match)
        self.tray_stop.setEnabled(self.controller.running)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._restore_window()

    def _restore_window(self) -> None:
        self._synchronize_controller_state()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def handle_local_control(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute one authenticated, allow-listed command on the GUI thread."""

        action = str(request.get("action") or "").strip().casefold()
        request_id = request_fingerprint(request)

        def finish(
            ok: bool,
            code: str,
            message: str,
            **payload: Any,
        ) -> dict[str, Any]:
            try:
                self.local_control_audit.add(action, accepted=ok, code=code)
            except OSError:
                pass
            return {
                "ok": ok,
                "code": code,
                "message": message,
                "protocol_version": CONTROL_PROTOCOL_VERSION,
                "request_id": request_id,
                **payload,
            }

        if str(request.get("protocol_version") or "") != str(CONTROL_PROTOCOL_VERSION):
            return finish(False, "protocol_mismatch", "Versión de protocolo incompatible.")
        if not self.settings.allow_local_control:
            return finish(
                False,
                "control_disabled",
                "El control local está desactivado en Preferencias.",
            )
        if not self.local_control_credentials.authorize(request.get("token")):
            return finish(False, "unauthorized", "Credencial local no válida.")

        try:
            if action == "capabilities":
                return finish(
                    True,
                    "ok",
                    "Capacidades locales disponibles.",
                    actions=[
                        "capabilities",
                        "status",
                        "set_source",
                        "set_hotwords",
                        "start",
                        "stop",
                        "transcript",
                        "alerts",
                        "show",
                    ],
                    limits={"transcript": 200, "alerts": 200, "hotwords": 100},
                )
            if action == "status":
                return finish(
                    True,
                    "ok",
                    "Estado consultado.",
                    status=self._local_control_status(),
                )
            if action == "set_source":
                if self.controller.running:
                    return finish(
                        False,
                        "monitoring_active",
                        "Detén el monitoreo antes de cambiar la fuente.",
                    )
                source = self._validate_control_source(request.get("source"))
                index = self.source_kind.findData("url")
                self.source_kind.setCurrentIndex(max(0, index))
                self.source_input.setText(source)
                fallback = fallback_source_info(source)
                self._current_source_title = fallback.title
                self.settings.source_kind = "url"
                self.settings.source_url = source
                self.settings.source_title = fallback.title
                self._source_kind_changed()
                self.store.save(self._collect_settings())
                return finish(
                    True,
                    "ok",
                    "Fuente actualizada para la siguiente sesión.",
                    source=redact_source(source),
                )
            if action == "set_hotwords":
                hotwords = self._validate_control_hotwords(request.get("hotwords"))
                self.settings.hotwords = hotwords
                self.hotword_editor.set_hotwords(hotwords)
                self.controller.update_hotwords(hotwords)
                self.store.save(self._collect_settings())
                return finish(
                    True,
                    "ok",
                    "Hotwords actualizadas.",
                    count=len(hotwords),
                )
            if action == "start":
                if self.controller.running:
                    return finish(
                        False,
                        "already_monitoring",
                        "El monitoreo ya está activo.",
                    )
                self.start_monitoring(interactive=False)
                return finish(
                    True,
                    "accepted",
                    "Inicio solicitado.",
                    status=self._local_control_status(),
                )
            if action == "stop":
                if not self.controller.running:
                    return finish(
                        False,
                        "not_monitoring",
                        "No hay un monitoreo activo.",
                    )
                self.stop_monitoring()
                return finish(
                    True,
                    "accepted",
                    "Detención solicitada.",
                    status=self._local_control_status(),
                )
            if action == "transcript":
                limit = self._control_limit(request.get("limit"), default=50)
                entries = self.controller.transcript_entries[-limit:]
                return finish(
                    True,
                    "ok",
                    "Transcripción reciente consultada.",
                    entries=[
                        {
                            "elapsed_seconds": item.elapsed_seconds,
                            "end_seconds": item.end_seconds,
                            "speaker": item.speaker_id,
                            "text": item.text[:2_000],
                            "confidence": item.confidence,
                            "hotwords": list(item.hotwords),
                            "created_at": item.created_at.astimezone().isoformat(),
                        }
                        for item in entries
                    ],
                    returned=len(entries),
                    total=len(self.controller.transcript_entries),
                )
            if action == "alerts":
                limit = self._control_limit(request.get("limit"), default=25)
                records = self.alert_history.records()[:limit]
                return finish(
                    True,
                    "ok",
                    "Alertas recientes consultadas.",
                    alerts=[self._safe_control_alert(item) for item in records],
                    returned=len(records),
                    total=len(self.alert_history.records()),
                )
            if action == "show":
                self._restore_window()
                return finish(True, "ok", "Ventana restaurada.")
            return finish(False, "unknown_action", "Acción local no permitida.")
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            return finish(False, "command_failed", redact_text(exc)[:500])

    def _local_control_status(self) -> dict[str, Any]:
        elapsed = 0
        if self._stopped_elapsed is not None:
            elapsed = self._stopped_elapsed
        elif self._started_monotonic is not None:
            elapsed = int(max(0.0, time.monotonic() - self._started_monotonic))
        return {
            "version": __version__,
            "state": self._current_state.value,
            "monitoring": self.controller.running,
            "source_kind": str(self.source_kind.currentData() or "url"),
            "source": redact_source(self._runtime_source_label()),
            "source_title": self._current_source_title,
            "elapsed_seconds": elapsed,
            "transcript_fragments": len(self.controller.transcript_entries),
            "alert_count": len(self.alert_history.records()),
            "hotwords": [
                {
                    "phrase": item.phrase,
                    "enabled": item.enabled,
                    "threshold": item.threshold,
                    "speaker_profile": item.speaker_profile,
                }
                for item in self.settings.hotwords
            ],
            "status_label": self.status_label.text(),
        }

    @staticmethod
    def _validate_control_source(value: object) -> str:
        source = str(value or "").strip()
        if not source or len(source) > 4_096:
            raise ValueError("La fuente debe contener entre 1 y 4.096 caracteres.")
        if source.startswith("demo://"):
            return source
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                "El control local solo admite enlaces HTTP/HTTPS. Los archivos y dispositivos se eligen manualmente."
            )
        return source

    def _validate_control_hotwords(self, value: object) -> list[Hotword]:
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("hotwords debe ser una lista de hasta 100 elementos.")
        known_profiles = set(self.speaker_profiles.names())
        result: list[Hotword] = []
        seen: set[str] = set()
        for raw in value:
            data = {"phrase": raw} if isinstance(raw, str) else raw
            if not isinstance(data, dict):
                raise ValueError("Cada hotword debe ser texto o un objeto.")
            phrase = str(data.get("phrase") or "").strip()
            if not phrase or len(phrase) > 120:
                raise ValueError("Cada hotword debe contener entre 1 y 120 caracteres.")
            key = phrase.casefold()
            if key in seen:
                continue
            seen.add(key)
            threshold = int(data.get("threshold", 88))
            if not 50 <= threshold <= 100:
                raise ValueError("El umbral de una hotword debe estar entre 50 y 100.")
            speaker = str(data.get("speaker_profile") or "").strip()
            if speaker and speaker not in known_profiles:
                raise ValueError(f"El perfil de voz '{speaker}' no existe.")
            result.append(
                Hotword(
                    phrase=phrase,
                    enabled=bool(data.get("enabled", True)),
                    threshold=threshold,
                    speaker_profile=speaker,
                )
            )
        return result

    @staticmethod
    def _control_limit(value: object, *, default: int) -> int:
        try:
            return max(1, min(200, int(value or default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_control_alert(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "detected_at": str(record.get("detected_at") or ""),
            "phrase": str(record.get("phrase") or ""),
            "score": float(record.get("score") or 0.0),
            "elapsed_seconds": float(record.get("elapsed_seconds") or 0.0),
            "context": str(record.get("context") or "")[:2_000],
            "matched_text": str(record.get("matched_text") or "")[:2_000],
            "speaker": str(record.get("speaker_id") or ""),
            "source": redact_source(str(record.get("source") or "")),
            "has_audio_clip": bool(record.get("audio_clip")),
            "has_video_clip": bool(record.get("video_clip")),
        }

    def _synchronize_controller_state(self) -> None:
        engine = getattr(self.controller, "engine", None)
        engine_state = getattr(engine, "state", None)
        if isinstance(engine_state, SessionState) and engine_state != self._current_state:
            self._set_state(engine_state)
            return
        self._update_tray_menu()
        self._write_runtime_status()

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self.tray_mute.setText("Activar alertas" if self._muted else "Silenciar alertas")
        self.tray_mute.setIcon(
            aw_icon("fa6s.volume-xmark" if self._muted else "fa6s.volume-high")
        )

    def _request_quit(self) -> None:
        self._quitting = True
        self.close()

    def _resolve_unsaved_transcript(self, title: str) -> bool:
        if not self.controller.transcript_dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText("La transcripción actual todavía no se ha guardado.")
        save = box.addButton("Guardar", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save_transcript()
        if box.clickedButton() is discard:
            self.controller.discard_recovered_transcript()
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.controller.running and not self._quitting:
            box = QMessageBox(self)
            box.setWindowTitle("AuralWarden está monitoreando")
            box.setText("¿Quieres mantener el monitoreo en segundo plano?")
            minimize = box.addButton(
                "Seguir en segundo plano", QMessageBox.ButtonRole.AcceptRole
            )
            stop_exit = box.addButton("Detener y salir", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is minimize:
                self.preview.stop()
                self.preview_panel.set_preview_active(False)
                self.hide()
                if QSystemTrayIcon.isSystemTrayAvailable():
                    self.tray.showMessage(
                        "AuralWarden sigue vigilando",
                        "La ventana está oculta; las alertas y los clips continúan activos.",
                        QSystemTrayIcon.MessageIcon.Information,
                        4_000,
                    )
                event.ignore()
                return
            if box.clickedButton() is not stop_exit:
                event.ignore()
                return
            self._quitting = True
        if self.controller.running:
            self.controller.stop()
            self.preview.stop()
            self._restore_silent_audio("La salida se restauró al detener la captura.")
            if not self._close_pending:
                self._close_pending = True
                QTimer.singleShot(100, self._finish_pending_close)
            self._status_detail = "Finalizando el audio, la transcripción y los clips antes de cerrar."
            self.status_label.setToolTip(self._status_detail)
            event.ignore()
            return
        if not self._resolve_unsaved_transcript("Antes de cerrar AuralWarden"):
            self._quitting = False
            self._close_pending = False
            event.ignore()
            return
        self.preview.stop()
        self._restore_silent_audio("La salida se restauró al cerrar AuralWarden.")
        self.controller.close()
        self.tray.hide()
        try:
            self.runtime_status.write(
                self._current_state,
                application_open=False,
                source=redact_source(self._runtime_source_label()),
                detail="AuralWarden se cerró.",
                session_path=self.controller.session_path,
            )
        except OSError:
            pass
        event.accept()
        QApplication.instance().quit()

    def _finish_pending_close(self) -> None:
        if not self._close_pending:
            return
        if self.controller.running:
            QTimer.singleShot(200, self._finish_pending_close)
            return
        self._close_pending = False
        self.close()

    def _write_runtime_status(self) -> None:
        try:
            self.runtime_status.write(
                self._current_state,
                source=redact_source(self._runtime_source_label()),
                detail=redact_text(self._status_detail),
                session_path=self.controller.session_path,
            )
        except OSError:
            return

    def _runtime_source_label(self) -> str:
        if not hasattr(self, "source_kind"):
            return self.settings.source_url
        kind = str(self.source_kind.currentData() or "url")
        if kind == "system_audio":
            return f"system_audio://{self.source_device.currentData() or 'predeterminado'}"
        if kind == "microphone":
            return f"microphone://{self.source_device.currentData() or 'predeterminado'}"
        return self.source_input.text().strip()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        scale = max(90, min(125, int(self.settings.interface_scale_percent))) / 100.0
        if hasattr(self, "privacy_label"):
            self.privacy_label.setVisible(self.width() >= round(1280 * scale))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.settings.minimize_to_tray
        ):
            self.preview.stop()
            self.preview_panel.set_preview_active(False)
            QTimer.singleShot(0, self.hide)
