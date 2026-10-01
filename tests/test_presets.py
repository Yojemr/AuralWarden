from pathlib import Path

from auralwarden.models import AppSettings, Hotword
from auralwarden.presets import PresetStore


def test_custom_preset_preserves_source_privacy_and_applies_options(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "presets.json")
    original = AppSettings(
        source_url="https://private.example/live",
        system_audio_device="Dispositivo personal",
        hotwords=[Hotword("asistencia")],
        clip_pre_seconds=22,
        performance_mode="precision",
    )
    store.save("Mi configuración", original)

    raw = (tmp_path / "presets.json").read_text(encoding="utf-8")
    assert "private.example" not in raw
    assert "Dispositivo personal" not in raw

    current = AppSettings(source_url="https://other.example/live")
    applied = store.apply("Mi configuración", current)
    assert applied.source_url == "https://other.example/live"
    assert applied.hotwords == [Hotword("asistencia")]
    assert applied.clip_pre_seconds == 22
    assert applied.performance_mode == "precision"


def test_built_in_preset_keeps_hotwords_and_source(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "presets.json")
    current = AppSettings(
        source_url="demo://keep",
        hotwords=[Hotword("termino sintetico")],
    )

    applied = store.apply("Bajo consumo", current)

    assert applied.source_url == "demo://keep"
    assert applied.hotwords == [Hotword("termino sintetico")]
    assert applied.performance_mode == "low_power"
    assert applied.dynamic_load_adaptation is True
