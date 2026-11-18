from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from auralwarden.local_control import (
    CONTROL_PROTOCOL_VERSION,
    LocalControlAuditStore,
    LocalControlCredentialStore,
    redact_source,
    redact_text,
)
from auralwarden.models import AppSettings, Hotword
from auralwarden.settings_store import SettingsStore
from auralwarden.ui.main_window import MainWindow


def test_control_selects_fresh_window_and_routes_only_the_monitored_application(tmp_path, monkeypatch):
    from auralwarden.models import SessionState
    from auralwarden.process_audio import ProcessPcmCapture, ProcessTarget
    from auralwarden.ui import main_window as ui
    from auralwarden.window_video import WindowTarget

    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(allow_local_control=True))
    window = MainWindow(settings_store=store)
    chrome = WindowTarget(10, 11, 12.0, "Synthetic Chrome", r"C:\Mock\chrome.exe")
    brave = WindowTarget(20, 21, 22.0, "Synthetic Brave", r"C:\Mock\brave.exe")
    monkeypatch.setattr(ui, "list_capture_windows", lambda: [chrome, brave])
    resolve = Mock(return_value=brave)
    monkeypatch.setattr(ui, "window_target", resolve)
    enumerate_outputs = Mock(return_value=[object()])
    monkeypatch.setattr(ui, "list_virtual_outputs", enumerate_outputs)

    def invoke(action, **payload):
        return window.handle_local_control(_request(window, action, **payload))

    selected = invoke("list_windows", application="CHROME.EXE")["windows"]
    assert len(selected) == 1 and selected[0]["application"] == "chrome"
    assert set(selected[0]) == {"id", "application", "title"}
    source = {"kind": "application_audio", "window_id": selected[0]["id"]}
    assert not invoke("select_windows_source", **source)["ok"]
    assert window.source_kind.currentData() == "url"
    resolve.return_value = chrome
    assert invoke("select_windows_source", **source)["ok"]
    assert window._selected_window_target == chrome
    assert not invoke("separate_audio", application="chrome", confirmed=True)["ok"]
    assert not enumerate_outputs.called

    target = ProcessTarget.from_window(chrome)
    state = {"phase": "requested", "lease": "synthetic-route"}
    router = Mock(active=False, state=state, status_message="")
    router.activate.return_value = "synthetic-route"
    router.recover_interrupted.return_value = True
    monkeypatch.setattr(window, "application_router", router)
    monkeypatch.setattr(window, "controller", SimpleNamespace(
        running=True, engine=SimpleNamespace(source=ProcessPcmCapture(target)),
        session_path=None, transcript_entries=(),
    ))
    window._current_state = SessionState.RUNNING
    window._last_audio_level = 0.2
    assert not invoke("separate_audio", application="chrome", confirmed=1)["ok"]
    assert not invoke("separate_audio", application="brave", confirmed=True)["ok"]
    assert not enumerate_outputs.called
    result = invoke("separate_audio", application="chrome", confirmed=True)
    assert result["code"] == "accepted" and result["audio_route"]["phase"] == "requested"
    router.activate.assert_called_once_with(target, enumerate_outputs.return_value[0], wait=False)
    window._check_control_audio_route("other")
    router.restore_original.assert_not_called()
    window._check_control_audio_route("synthetic-route")
    router.restore_original.assert_called_once_with(wait=False)
    state["phase"] = "active"
    assert invoke("status")["status"]["audio_route"]["phase"] == "active"
    assert invoke("restore_audio")["code"] == "accepted"
    router.recover_interrupted.assert_called_once()


def test_control_windows_devices_configuration_timer_and_export(tmp_path, monkeypatch):
    from auralwarden.models import TranscriptEntry
    from auralwarden.ui import main_window as ui
    from auralwarden.windows_audio import WindowsAudioDevice

    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(allow_local_control=True))
    window = MainWindow(settings_store=store)
    inputs = [WindowsAudioDevice("Synthetic default", "microphone", True),
              WindowsAudioDevice("Synthetic selection", "microphone")]
    monkeypatch.setattr(ui, "list_windows_audio_devices", lambda kind: inputs)
    monkeypatch.setattr(ui, "transcripts_dir", lambda: tmp_path / "transcripts")

    def invoke(action, **payload):
        return window.handle_local_control(_request(window, action, **payload))

    assert len(invoke("list_audio_devices", kind="microphone")["devices"]) == 2
    assert invoke("select_windows_source", kind="microphone", device="Synthetic selection")["ok"]
    assert window.settings.microphone_device == "Synthetic selection"
    assert not invoke("configure_session", options={"clip_pre_seconds": 10, "save_full_video": True})["ok"]
    assert window.quick_settings.pre_seconds.value() != 10
    assert invoke("configure_session", options={"clip_pre_seconds": 10, "diarization": True})["ok"]
    assert window.settings.diarization_enabled
    assert invoke("set_stop_timer", duration_seconds=45)["timer"]["duration_seconds"] == 45
    assert invoke("set_stop_timer")["timer"]["duration_seconds"] is None
    window.controller._recovered_transcript.add(TranscriptEntry(0, "Speaker 1", "Texto sintético"))
    first = invoke("save_transcript")
    second = invoke("save_transcript")
    assert first["ok"] and second["ok"] and first["filename"] != second["filename"]
    assert "Texto sintético" in (tmp_path / "transcripts" / first["filename"]).read_text(encoding="utf-8")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _request(window: MainWindow, action: str, **payload: object) -> dict[str, object]:
    return {
        "protocol_version": CONTROL_PROTOCOL_VERSION,
        "token": window.local_control_credentials.read(),
        "action": action,
        **payload,
    }


def test_control_credentials_rotate_authorize_and_revoke(tmp_path: Path) -> None:
    store = LocalControlCredentialStore(tmp_path / "local-control.json")
    first = store.ensure()
    assert len(first) >= 32
    assert store.authorize(first)
    second = store.rotate()
    assert second != first
    assert not store.authorize(first)
    assert store.authorize(second)
    store.revoke()
    assert not store.authorize(second)


def test_control_audit_is_bounded_and_omits_arguments(tmp_path: Path) -> None:
    store = LocalControlAuditStore(tmp_path / "audit.json", max_records=20)
    for index in range(30):
        store.add("set_source", accepted=index % 2 == 0, code="ok")
    records = store.records()
    assert len(records) == 20
    assert set(records[0]) == {"occurred_at", "action", "accepted", "code"}
    audit_text = (tmp_path / "audit.json").read_text(encoding="utf-8")
    assert "arguments" not in audit_text
    assert "api_key" not in audit_text


def test_sources_and_diagnostic_urls_are_redacted() -> None:
    secret = "https://user:password@example.com/live.m3u8?api_key=private#section"
    assert redact_source(secret) == "https://example.com/live.m3u8"
    assert (
        redact_text(f"Falló {secret} durante la captura")
        == "Falló https://example.com/live.m3u8 durante la captura"
    )


def test_local_control_is_disabled_by_default(tmp_path: Path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="demo://disabled"))
    window = MainWindow(settings_store=store)
    try:
        response = window.handle_local_control(
            {
                "protocol_version": CONTROL_PROTOCOL_VERSION,
                "token": "anything",
                "action": "status",
            }
        )
        assert response["ok"] is False
        assert response["code"] == "control_disabled"
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_local_control_updates_source_and_hotwords_without_exposing_secret(
    tmp_path: Path,
) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        AppSettings(
            source_url="demo://enabled",
            allow_local_control=True,
            hotwords=[Hotword("ayuda")],
        )
    )
    window = MainWindow(settings_store=store)
    try:
        denied = window.handle_local_control(
            {
                "protocol_version": CONTROL_PROTOCOL_VERSION,
                "token": "wrong",
                "action": "status",
            }
        )
        assert denied["code"] == "unauthorized"

        source = "https://example.com/live.m3u8?api_key=private"
        changed = window.handle_local_control(
            _request(window, "set_source", source=source)
        )
        assert changed["ok"] is True
        assert changed["source"] == "https://example.com/live.m3u8"
        assert "private" not in json.dumps(changed)
        assert window.source_input.text() == source

        hotwords = window.handle_local_control(
            _request(
                window,
                "set_hotwords",
                hotwords=[
                    {"phrase": "palabra clave", "threshold": 91},
                    "asistencia",
                ],
            )
        )
        assert hotwords["ok"] is True
        assert [item.phrase for item in window.settings.hotwords] == [
            "palabra clave",
            "asistencia",
        ]

        status = window.handle_local_control(_request(window, "status"))
        assert status["status"]["source"] == "https://example.com/live.m3u8"
        assert "private" not in json.dumps(status)
        assert "token" not in json.dumps(status).casefold()

        audit_text = (tmp_path / "local-control-audit.json").read_text(
            encoding="utf-8"
        )
        assert "private" not in audit_text
        assert "palabra clave" not in audit_text
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_local_control_rejects_files_and_bounds_reads(tmp_path: Path) -> None:
    app = _app()
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(allow_local_control=True))
    window = MainWindow(settings_store=store)
    try:
        local_file = window.handle_local_control(
            _request(window, "set_source", source="C:/Users/example/private.wav")
        )
        assert local_file["ok"] is False
        assert local_file["code"] == "command_failed"

        transcript = window.handle_local_control(
            _request(window, "transcript", limit=100_000)
        )
        assert transcript["ok"] is True
        assert transcript["entries"] == []

        capabilities = window.handle_local_control(
            _request(window, "capabilities")
        )
        assert capabilities["limits"]["transcript"] == 200
        assert "run_command" not in capabilities["actions"]
    finally:
        window.tray.hide()
        window.deleteLater()
        app.processEvents()
