from __future__ import annotations

import json
from pathlib import Path

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
