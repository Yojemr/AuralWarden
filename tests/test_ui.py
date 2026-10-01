from __future__ import annotations

import os
import json
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from auralwarden import __version__
from auralwarden.alert_history import AlertHistoryStore
from auralwarden.models import AppSettings, EngineEvent, EventKind, Hotword, SessionState
from auralwarden.settings_store import SettingsStore
from auralwarden.presets import PresetStore
from auralwarden.session import SessionWorkspace
from auralwarden.source_info import SourceInfo
from auralwarden.ui import controller as controller_module
from auralwarden.ui import dialogs as dialogs_module
from auralwarden.ui import main_window as main_window_module
from auralwarden.ui.dialogs import PreferencesDialog, SpeakerNamesDialog
from auralwarden.ui.management_dialogs import (
    AlertHistoryDialog,
    PresetDialog,
    TranscriptLibraryDialog,
)
from auralwarden.ui.app import (
    SingleInstanceGuard,
    configure_application_identity,
    single_instance_name,
)
from auralwarden.ui.main_window import MainWindow
from auralwarden.ui.widgets import (
    ActivityFeed,
    CaptionPreviewPanel,
    HotwordEditor,
    PreviewPanel,
    TranscriptFeed,
    aw_icon,
)


def test_remote_title_and_caption_are_always_plain_text() -> None:
    app = QApplication.instance() or QApplication([])
    preview = PreviewPanel()
    captions = CaptionPreviewPanel()
    attack = '<img src="file:///C:/sensitive.png"> harmless'
    preview.set_title(attack, "<b>channel</b>")
    captions.add_cue(attack, 1.0)
    app.processEvents()
    assert preview.title_label.textFormat() == Qt.TextFormat.PlainText
    assert captions.text_label.textFormat() == Qt.TextFormat.PlainText
    assert preview.title_label.text() == attack
    assert "<" not in preview.title_label.toolTip()
    assert attack in captions.text_label.text()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_clip_switches_reach_active_engine_and_restore_after_stop(tmp_path):
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="https://video.example/live", save_event_video_clips=True))
    window = MainWindow(settings_store=store)
    calls = []
    engine = SimpleNamespace(running=True, worker_alive=False, state=SessionState.RUNNING, session=None,
                             video_capture_available=True,
                             update_clip_preferences=lambda audio, video: calls.append((audio, video)))
    window.controller.engine = engine
    try:
        window._set_state(SessionState.RUNNING)
        assert not window.quick_settings.save_full_video.isEnabled()
        assert window.quick_settings.save_event_video_clips.isEnabled()
        window.quick_settings.save_event_video_clips.click()
        window.quick_settings.save_event_video_clips.click()
        assert [video for _, video in calls] == [False, True]
        engine.running = False
        window._set_state(SessionState.STOPPED)
        assert window.quick_settings.save_full_video.isEnabled()
        engine.video_capture_available = False
        engine.running = True
        window._set_state(SessionState.RUNNING)
        assert not window.quick_settings.save_event_video_clips.isEnabled()
    finally:
        window.controller.engine = None
        window._quitting = True
        window.close()
        window.deleteLater()
        app.processEvents()


def test_portable_icon_font_does_not_require_windows_installation() -> None:
    _app()
    icon = aw_icon("fa6s.play", "#ffffff")
    assert not icon.isNull()
    assert not icon.pixmap(24, 24).isNull()


def test_preset_and_history_dialogs_render_and_filter(tmp_path: Path) -> None:
    app = _app()
    preset_dialog = PresetDialog(
        PresetStore(tmp_path / "presets.json"), AppSettings()
    )
    history_store = AlertHistoryStore(tmp_path / "history.json")
    history_store.add_detection(
        {"event_id": "evt-1", "phrase": "asistencia", "speaker_id": "Ana"},
        source_title="Reunión",
    )
    history_dialog = AlertHistoryDialog(history_store)
    try:
        assert preset_dialog.list_widget.count() >= 3
        preset_dialog.list_widget.setCurrentRow(0)
        preset_dialog._apply()
        assert preset_dialog.selected_name == "Máxima detección"

        assert history_dialog.table.rowCount() == 1
        history_dialog.search.setText("no existe")
        app.processEvents()
        assert history_dialog.table.rowCount() == 0
        history_dialog.search.setText("Ana")
        app.processEvents()
        assert history_dialog.table.rowCount() == 1
    finally:
        preset_dialog.deleteLater()
        history_dialog.deleteLater()
        app.processEvents()


def test_transcript_library_reads_saved_json_inside_the_app(tmp_path: Path) -> None:
    app = _app()
    session = tmp_path / "sessions" / "2026-08-31_10-00-00 - Reunión"
    transcripts = session / "transcripts"
    transcripts.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "title": "Reunión de prueba",
                "started_at": "2026-08-31T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    (transcripts / "2026-08-31_10-00-00 - Transcripcion.json").write_text(
        json.dumps(
            [
                {
                    "elapsed_seconds": 10,
                    "end_seconds": 12,
                    "speaker_id": "Ana",
                    "text": "Texto fácil de leer",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dialog = TranscriptLibraryDialog(tmp_path / "sessions")
    try:
        assert dialog.list_widget.count() == 1
        assert dialog.title_label.text() == "Reunión de prueba"
        assert "[00:00:10] Ana" in dialog.viewer.toPlainText()
        assert "Texto fácil de leer" in dialog.viewer.toPlainText()
        assert "{" not in dialog.viewer.toPlainText()
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_activity_card_can_open_each_ready_evidence() -> None:
    app = _app()
    feed = ActivityFeed()
    opened: list[str] = []
    feed.open_requested.connect(opened.append)
    try:
        feed.add_detection({"event_id": "evt", "phrase": "ayuda"})
        feed.mark_clip(
            {"event_id": "evt", "path": "C:/clips/ayuda.mp4", "media_type": "video/mp4"}
        )
        card = feed._by_event["evt"]
        card._media_buttons["video/mp4"].click()
        assert opened == ["C:/clips/ayuda.mp4"]
    finally:
        feed.deleteLater()
        app.processEvents()


def test_caption_preview_keeps_only_recent_auxiliary_cues() -> None:
    app = _app()
    panel = CaptionPreviewPanel()
    try:
        panel.set_option_visible(True)
        panel.begin()
        panel.set_track("es", True)
        for index in range(4):
            panel.add_cue(f"Subtítulo {index}", index)
        text = panel.text_label.text()
        assert panel.isVisible()
        assert panel.status_label.text() == "Recibiendo"
        assert "Subtítulo 0" not in text
        assert "Subtítulo 1" in text
        assert "Subtítulo 3" in text
    finally:
        panel.deleteLater()
        app.processEvents()


def test_caption_preview_explains_waiting_and_retrying_states() -> None:
    app = _app()
    panel = CaptionPreviewPanel()
    try:
        panel.set_option_visible(True)
        panel.begin()
        panel.set_waiting("YouTube aún no publica la pista.", 5)
        assert panel.status_label.text() == "Esperando pista"
        assert "5 s" in panel.text_label.text()

        panel.set_retrying("Se volverá a consultar.", 10)
        assert panel.status_label.text() == "Reintentando · 10 s"
        assert "sin detener Whisper" in panel.text_label.text()

        panel.set_unavailable("Todavía no existe.", retrying=True)
        assert panel.status_label.text() == "No disponibles · reintentando"
        assert "seguirá consultándola" in panel.text_label.text()
    finally:
        panel.deleteLater()
        app.processEvents()


def test_caption_preview_is_fixed_above_the_scrolling_transcript() -> None:
    app = _app()
    feed = TranscriptFeed()
    try:
        layout = feed.layout()
        assert feed.caption_preview.parent() is feed
        assert layout.indexOf(feed.caption_preview) < layout.indexOf(feed.scroll)
    finally:
        feed.deleteLater()
        app.processEvents()


def test_windows_title_does_not_append_application_name() -> None:
    app = _app()
    configure_application_identity(app)
    assert app.applicationName() == "AuralWarden"
    assert app.applicationDisplayName() == ""


def test_hotword_fields_have_room_and_explain_their_effect() -> None:
    app = _app()
    editor = HotwordEditor()
    try:
        editor.add_hotword(Hotword("palabra clave"))
        phrase = editor.table.cellWidget(0, 0)
        threshold = editor.table.cellWidget(0, 1)
        assert editor.table.rowHeight(0) >= 48
        assert phrase.minimumHeight() >= 38
        assert threshold.minimumHeight() >= 38
        assert phrase.toolTip()
        assert threshold.toolTip()
    finally:
        editor.deleteLater()
        app.processEvents()


def test_removing_hotword_queues_live_detector_update(tmp_path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://hotword-update", hotwords=[Hotword("ayuda")]))
    window = MainWindow(settings_store=store)
    updates: list[list[Hotword]] = []
    original_update = window.controller.update_hotwords
    window.controller.update_hotwords = updates.append
    try:
        remove = window.hotword_editor.table.cellWidget(0, 3)
        remove.click()

        assert window._hotword_update_timer.isActive()
        window._hotword_update_timer.stop()
        window._apply_hotword_changes()

        assert updates == [[]]
        assert store.load().hotwords == []
    finally:
        window.controller.update_hotwords = original_update
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_preferences_fields_have_contextual_tooltips() -> None:
    app = _app()
    dialog = PreferencesDialog(AppSettings())
    try:
        fields = [
            dialog.model,
            dialog.language,
            dialog.performance_mode,
            dialog.backend,
            dialog.device,
            dialog.compute_type,
            dialog.hardware_status,
            dialog.analyze_hardware,
            dialog.window,
            dialog.overlap,
            dialog.low_confidence,
            dialog.context,
            dialog.vocabulary,
            dialog.preview_mode,
            dialog.audio_buffer,
            dialog.video_buffer,
            dialog.merge_nearby,
            dialog.auto_save,
            dialog.minimize_to_tray,
            dialog.dynamic_load_adaptation,
            dialog.interface_scale,
            dialog.allow_local_control,
            dialog.reconnect_enabled,
            dialog.reconnect_attempts,
            dialog.reconnect_initial_delay,
            dialog.reconnect_max_delay,
            dialog.diarization_root,
            dialog.cluster_threshold,
            dialog.speaker_threshold,
            dialog.voice_profile_threshold,
            dialog.diarization_threads,
            dialog.whisper_cpp_executable,
            dialog.install_whisper_cpp,
            dialog.whisper_cpp_model,
            dialog.whisper_cpp_acceleration,
        ]
        assert all(field.toolTip().strip() for field in fields)
        assert not dialog.allow_local_control.isChecked()
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_hardware_analysis_summary_has_room_for_wrapped_text(monkeypatch) -> None:
    app = _app()
    dialog = PreferencesDialog(AppSettings())
    summary = (
        "8 núcleos físicos, 32 GB RAM; AMD Radeon Graphics, NVIDIA RTX 3060. "
        "Recomendación: faster_whisper / cuda / float16. CUDA está disponible."
    )
    monkeypatch.setattr(dialogs_module, "detect_hardware", lambda *_: object())
    monkeypatch.setattr(
        dialogs_module,
        "select_inference_plan",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(dialogs_module, "hardware_summary", lambda *_: summary)
    try:
        dialog._analyze_hardware()
        dialog.show()
        app.processEvents()
        assert dialog.hardware_status.text() == summary
        assert dialog.hardware_status.height() >= 76
        assert dialog.hardware_panel.minimumHeight() >= 76
        assert dialog.minimumHeight() >= 660
        assert "#48d7aa" in dialog.hardware_status.styleSheet()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_waiting_and_reconnecting_are_visible_monitoring_states(tmp_path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://states"))
    window = MainWindow(settings_store=store)
    try:
        window._set_state(SessionState.WAITING)
        assert window.status_label.text() == "Esperando directo"
        assert window.stop_button.isEnabled()
        window._set_state(SessionState.RECONNECTING)
        assert window.status_label.text() == "Reconectando"
        assert window.stop_button.isEnabled()
        window._set_state(SessionState.STOPPED)
        assert window.status_label.text() == "Sesión detenida"
        assert not window.stop_button.isEnabled()
        runtime = json.loads(
            (tmp_path / "runtime-status.json").read_text(encoding="utf-8")
        )
        assert runtime["application_open"] is True
        assert runtime["monitoring"] is False
        assert runtime["state"] == "stopped"
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_state_guard_repairs_stale_visible_state(tmp_path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://state-guard"))
    window = MainWindow(settings_store=store)
    try:
        window.controller.engine = SimpleNamespace(
            state=SessionState.RUNNING, running=True, session=None
        )
        window._set_state(SessionState.IDLE)
        window._synchronize_controller_state()
        assert window._current_state == SessionState.RUNNING
        assert window.status_label.text() == "Monitoreo activo"
        runtime = json.loads(
            (tmp_path / "runtime-status.json").read_text(encoding="utf-8")
        )
        assert runtime["monitoring"] is True
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_sound_and_notification_can_be_previewed(tmp_path, monkeypatch) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://alerts"))
    sounds: list[str] = []
    notices: list[dict[str, object]] = []
    monkeypatch.setattr(
        MainWindow,
        "_play_notification_sound",
        staticmethod(lambda name: sounds.append(name)),
    )
    window = MainWindow(settings_store=store)
    monkeypatch.setattr(
        window,
        "_emit_notification",
        lambda _title, _message, **options: notices.append(options),
    )
    try:
        window.quick_settings.sound.setCurrentText("Aviso")
        window.quick_settings.test_sound.click()
        assert sounds == ["Asterisk"]

        window.quick_settings.notification_mode.setCurrentText("Solo Windows")
        window.quick_settings.test_notification.click()
        assert notices == [
            {"desktop": True, "sound": False, "sound_name": "Asterisk"}
        ]
        assert window.quick_settings.test_sound.toolTip()
        assert window.quick_settings.test_notification.toolTip()
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_notification_profiles_use_distinct_local_audio_files() -> None:
    from auralwarden.ui.assets import asset_path

    paths = [
        asset_path("notification-friendly.wav"),
        asset_path("notification-notice.wav"),
        asset_path("notification-discreet.wav"),
    ]
    assert all(path.is_file() for path in paths)
    assert len({path.read_bytes() for path in paths}) == 3


def test_hotword_can_be_limited_to_saved_voice_profile() -> None:
    app = _app()
    editor = HotwordEditor()
    try:
        editor.set_speaker_profiles(["Ana", "Carlos"])
        editor.add_hotword(
            Hotword("asistencia", threshold=90, speaker_profile="Ana")
        )
        assert editor.hotwords() == [
            Hotword("asistencia", threshold=90, speaker_profile="Ana")
        ]
        selector = editor.table.cellWidget(0, 2)
        assert selector.currentText() == "Ana"
        assert selector.toolTip()
    finally:
        editor.deleteLater()
        app.processEvents()


def test_speaker_dialog_enrolls_and_removes_voluntary_profiles() -> None:
    app = _app()
    dialog = SpeakerNamesDialog(
        [("Speaker 1", "Speaker 1")],
        {},
        {"Speaker 1"},
        ["Ana"],
    )
    try:
        dialog.inputs["Speaker 1"].setText("Carlos")
        dialog.profile_checks["Speaker 1"].setChecked(True)
        dialog.delete_checks["Ana"].setChecked(True)
        assert dialog.mapping() == {"Speaker 1": "Carlos"}
        assert dialog.profile_requests() == {"Speaker 1": "Carlos"}
        assert dialog.profile_deletions() == ["Ana"]
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_single_instance_name_is_stable_per_portable_root(tmp_path) -> None:
    first = single_instance_name(tmp_path / "AuralWarden-0.6.0")
    assert first == single_instance_name(tmp_path / "AuralWarden-0.6.0")
    assert first != single_instance_name(tmp_path / "AuralWarden-0.5.1")


def test_second_instance_signals_existing_local_server(tmp_path) -> None:
    _app()
    name = single_instance_name(tmp_path / "AuralWarden-single-instance-test")
    first = SingleInstanceGuard(name)
    second = SingleInstanceGuard(name)
    try:
        assert first.claim() is True
        assert second.claim() is False
    finally:
        second.close()
        first.close()


def test_transcript_feed_groups_consecutive_fragments_into_paragraphs() -> None:
    app = _app()
    feed = TranscriptFeed()
    try:
        feed.append_entry(
            {"elapsed_seconds": 180, "end_seconds": 184, "speaker_id": "Speaker 1", "text": "Primera parte"}
        )
        feed.append_entry(
            {"elapsed_seconds": 184, "end_seconds": 188, "speaker_id": "Speaker 1", "text": "que continúa la idea."}
        )
        assert feed._paragraph_count == 1
        assert feed._last_row is not None
        assert feed._last_row.plain_text == "Primera parte que continúa la idea."
        assert feed._last_row.fragment_time_text("awtime:0") == (
            "Fragmento: 00:03:00–00:03:04"
        )
        assert feed._last_row.fragment_time_text("awtime:1") == (
            "Fragmento: 00:03:04–00:03:08"
        )
        assert 'href="awtime:1"' in feed._last_row.text_label.text()

        feed.append_entry(
            {"elapsed_seconds": 179, "end_seconds": 181, "speaker_id": "Speaker 1", "text": "Dato anterior."}
        )
        assert feed._paragraph_count == 1
        assert feed._last_row.time_label.text() == "00:02:59"

        feed.append_entry(
            {"elapsed_seconds": 189, "speaker_id": "Speaker 2", "text": "Respuesta."}
        )
        feed.append_entry(
            {"elapsed_seconds": 205, "speaker_id": "Speaker 2", "text": "Nueva intervención."}
        )
        assert feed._paragraph_count == 3
        assert feed.count_label.text() == "5 fragmentos · 3 párrafos"

        feed.clear()
        feed.append_entry(
            {"elapsed_seconds": 1, "speaker_id": "Speaker 1", "text": "Después de limpiar."}
        )
        app.processEvents()
        assert feed._count == 1
        assert not any(
            label.text() == "La transcripción aparecerá aquí al iniciar el monitoreo."
            for label in feed.findChildren(type(feed.empty))
        )
    finally:
        feed.deleteLater()
        app.processEvents()


def test_main_window_settings_and_event_flow(tmp_path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url="demo://ui-test",
            hotwords=[Hotword("ayuda", threshold=86)],
            desktop_notifications=False,
            sound_notifications=False,
            diarization_enabled=False,
            save_event_video_clips=True,
        )
    )
    window = MainWindow(settings_store=store)
    try:
        assert window.source_input.text() == "demo://ui-test"
        assert [item.phrase for item in window.hotword_editor.hotwords()] == ["ayuda"]

        window._handle_event(
            EngineEvent(
                EventKind.TRANSCRIPT,
                {
                    "elapsed_seconds": 7.25,
                    "speaker_id": "Speaker 2",
                    "text": "Necesitamos ayuda para terminar la prueba.",
                    "hotwords": ["ayuda"],
                },
            )
        )
        window._handle_event(
            EngineEvent(
                EventKind.HOTWORD,
                {
                    "event_id": "ui-test-event",
                    "elapsed_seconds": 7.25,
                    "phrase": "ayuda",
                    "score": 100.0,
                    "context": "Necesitamos ayuda para terminar la prueba.",
                    "created": True,
                    "audio_clip_requested": True,
                    "video_clip_requested": True,
                },
            )
        )
        window._handle_event(
            EngineEvent(
                EventKind.CLIP,
                {
                    "event_id": "ui-test-event",
                    "path": str(tmp_path / "event.wav"),
                    "truncated": False,
                },
            )
        )
        window._handle_event(
            EngineEvent(
                EventKind.CLIP,
                {
                    "event_id": "ui-test-event",
                    "path": str(tmp_path / "event.mp4"),
                    "truncated": False,
                    "media_type": "video/mp4",
                },
            )
        )
        app.processEvents()

        assert "Speaker 2" in window._speakers
        assert len(window.activity._by_event) == 1
        assert window.last_event_label.text() == "Última alerta: ayuda · 100 %"
        assert window.clips_label.text() == "1 clip"
        assert window.quick_settings.save_event_video_clips.isChecked()
        assert (
            window.activity._by_event["ui-test-event"].clip_label.text()
            == "Clips de audio y vídeo creados"
        )
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_new_session_does_not_reuse_manual_speaker_names(tmp_path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url="demo://fresh-speakers",
            speaker_names={"Speaker 2": "Persona Alfa"},
            diarization_enabled=False,
        )
    )
    window = MainWindow(settings_store=store)
    started_with: list[dict[str, str]] = []
    original_start = window.controller.start
    window.controller.start = lambda settings: started_with.append(
        dict(settings.speaker_names)
    )
    try:
        assert window.start_monitoring(interactive=False)
        assert started_with == [{}]
        assert store.load().speaker_names == {}
    finally:
        window.controller.start = original_start
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_main_window_shows_identity_title_and_manual_preview(tmp_path) -> None:
    app = _app()

    class FakeEventSignal:
        def connect(self, _callback) -> None:
            return

    class FakeController:
        def __init__(self) -> None:
            self.event_received = FakeEventSignal()
            self.running = False
            self.transcript_dirty = False
            self.session_path = None

        def start(self, _settings) -> None:
            self.running = True

        def stop(self) -> None:
            self.running = False

        def stop_and_wait(self, _timeout=10.0) -> None:
            self.running = False

        def close(self) -> None:
            self.running = False

    class FakePreview:
        def __init__(self) -> None:
            self.active = False
            self.starts: list[tuple[str, bool, float]] = []

        def start(self, source: str, *, synced: bool, delay_seconds: float) -> None:
            self.active = True
            self.starts.append((source, synced, delay_seconds))

        def stop(self) -> None:
            self.active = False

    source = "https://www.youtube.com/watch?v=Ygt2rwVusTs"
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url=source,
            hotwords=[Hotword("ayuda")],
            desktop_notifications=False,
            sound_notifications=False,
            diarization_enabled=False,
        )
    )
    controller = FakeController()
    window = MainWindow(settings_store=store, controller=controller)
    original_preview = window.preview
    preview = FakePreview()
    window.preview = preview
    window.source_info.request = lambda _source: None
    try:
        assert window.version_label.text() == f"v{__version__} · Made by Yojemr"
        assert window.preview_panel.title_label.text() == "Directo de YouTube"

        window.start_monitoring()
        assert controller.running
        assert preview.starts == []
        assert window.preview_panel.preview_button.isEnabled()
        assert window.preview_panel.preview_button.text() == "Activar vista"

        window.toggle_preview()
        assert preview.active
        assert preview.starts == [(source, True, 6.0)]
        assert window.preview_panel.preview_button.text() == "Desactivar vista"

        window.toggle_preview()
        assert not preview.active
        assert window.preview_panel.preview_button.text() == "Activar vista"

        window._source_info_ready(
            source, SourceInfo("Entrevista en vivo", "Canal de prueba")
        )
        assert window.preview_panel.title_label.text() == "Entrevista en vivo"
        assert "Canal de prueba" in window.preview_panel.title_label.toolTip()
    finally:
        controller.stop()
        window.preview = original_preview
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_windows_notification_is_requested_for_new_match(tmp_path, monkeypatch) -> None:
    _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url="demo://notification-test",
            desktop_notifications=True,
            sound_notifications=False,
        )
    )
    window = MainWindow(settings_store=store)
    original_tray = window.tray
    calls: list[tuple[object, ...]] = []

    class FakeTrayApi:
        class MessageIcon:
            Information = "information"

        @staticmethod
        def isSystemTrayAvailable() -> bool:
            return True

    class FakeTray:
        def showMessage(self, *args) -> None:
            calls.append(args)

    try:
        monkeypatch.setattr(main_window_module, "QSystemTrayIcon", FakeTrayApi)
        window.tray = FakeTray()
        window._notify("ayuda", 96.0)
        assert calls
        assert calls[0][0] == "AuralWarden detectó una coincidencia"
        assert calls[0][1] == "ayuda · 96 %"
    finally:
        window.tray = original_tray
        original_tray.hide()
        window.deleteLater()


def test_closing_window_can_keep_monitoring_in_background(tmp_path, monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(controller_module, "sessions_dir", lambda: tmp_path / "sessions")
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url="demo://background-test",
            hotwords=[Hotword("ayuda")],
            desktop_notifications=False,
            sound_notifications=False,
            diarization_enabled=False,
            save_event_video_clips=False,
        )
    )
    window = MainWindow(settings_store=store)

    class BackgroundChoiceBox:
        ButtonRole = QMessageBox.ButtonRole

        def __init__(self, parent=None) -> None:
            self._selected = None

        def setWindowTitle(self, title: str) -> None:
            return

        def setText(self, text: str) -> None:
            return

        def addButton(self, text: str, role) -> object:
            button = object()
            if text == "Seguir en segundo plano":
                self._selected = button
            return button

        def exec(self) -> None:
            return

        def clickedButton(self):
            return self._selected

    try:
        window.start_monitoring()
        assert window.controller.running
        monkeypatch.setattr(main_window_module, "QMessageBox", BackgroundChoiceBox)
        event = QCloseEvent()

        window.closeEvent(event)

        assert not event.isAccepted()
        assert window.controller.running
    finally:
        window.controller.stop_and_wait()
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_files_menu_opens_separate_session_folders(tmp_path, monkeypatch) -> None:
    _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://folders"))
    window = MainWindow(settings_store=store)
    session = SessionWorkspace(tmp_path / "sessions", "demo://folders")
    window.controller.engine = SimpleNamespace(session=session)
    opened: list[Path] = []

    class FakeDesktopServices:
        @staticmethod
        def openUrl(url) -> bool:
            opened.append(Path(url.toLocalFile()))
            return True

    monkeypatch.setattr(main_window_module, "QDesktopServices", FakeDesktopServices)
    try:
        window._open_output_folder("video")
        window._open_output_folder("audio")
        window._open_output_folder("transcripts")

        assert opened == [
            session.video_clips_dir,
            session.audio_clips_dir,
            session.transcripts_dir,
        ]
        assert all(path.is_dir() for path in opened)
    finally:
        window.tray.hide()
        window.deleteLater()


def test_close_waits_for_final_transcript_before_save_prompt(tmp_path, monkeypatch):
    _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(desktop_notifications=False, sound_notifications=False))
    window = MainWindow(settings_store=store)
    engine = SimpleNamespace(worker_alive=True, running=True, transcript=SimpleNamespace(entries=[]),
                             stop=lambda: None)
    window.controller.engine = engine
    window._quitting = True
    asked = []
    monkeypatch.setattr(window, "_resolve_unsaved_transcript", lambda title: asked.append(title) or False)
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda *args: None)
    try:
        first = QCloseEvent()
        window.closeEvent(first)
        assert not first.isAccepted() and not asked
        engine.transcript.entries.append("synthetic final fragment")
        engine.worker_alive = False
        engine.running = False
        second = QCloseEvent()
        window.closeEvent(second)
        assert asked and window.controller.transcript_entries == ("synthetic final fragment",)
        assert not second.isAccepted()
    finally:
        window.controller.engine = None
        window.tray.hide()
        window.deleteLater()
