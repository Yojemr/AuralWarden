from __future__ import annotations

import json
from pathlib import Path

from auralwarden.source_info import fallback_source_info, resolve_source_info


class FakeResponse:
    def __init__(self, payload: dict[str, str]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_source_info_uses_local_names_without_network(tmp_path: Path) -> None:
    local = tmp_path / "entrevista.mp4"
    local.write_bytes(b"video")

    assert resolve_source_info(str(local)).title == "entrevista.mp4"
    assert fallback_source_info("demo://interfaz").title == (
        "Demostración de AuralWarden"
    )


def test_fallback_identifies_supported_platforms_and_radio() -> None:
    assert fallback_source_info("https://twitch.tv/example").title == "Directo de Twitch"
    assert fallback_source_info("https://kick.com/example").title == "Directo de Kick"
    radio = fallback_source_info("https://radio.example/live.mp3")
    assert radio.title == "Transmisión de audio"
    assert radio.author == "radio.example"


def test_youtube_title_is_resolved_through_public_oembed() -> None:
    calls: list[str] = []

    def opener(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 8.0
        return FakeResponse(
            {"title": "  Entrevista en vivo  ", "author_name": "Canal de prueba"}
        )

    info = resolve_source_info(
        "https://www.youtube.com/watch?v=Ygt2rwVusTs", opener=opener
    )

    assert info.title == "Entrevista en vivo"
    assert info.author == "Canal de prueba"
    assert calls and "youtube.com%2Fwatch" in calls[0]
