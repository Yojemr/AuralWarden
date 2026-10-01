from pathlib import Path

from auralwarden.models import AppSettings, Hotword
from auralwarden.settings_store import SettingsStore


def test_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = AppSettings(
        source_url="demo://test",
        source_kind="system_audio",
        system_audio_device="Altavoces [Loopback]",
        hotwords=[Hotword("ministerio")],
    )
    store.save(settings)
    restored = store.load()
    assert restored.source_url == "demo://test"
    assert restored.source_kind == "system_audio"
    assert restored.system_audio_device == "Altavoces [Loopback]"
    assert restored.hotwords[0].phrase == "ministerio"
    assert restored.transcription_window_seconds == 6.0
    assert restored.transcription_overlap_seconds == 2.0
    assert restored.low_confidence_second_pass_threshold == 0.62
    assert restored.schema_version == 12
    assert restored.dynamic_load_adaptation is True
    assert restored.interface_scale_percent == 100
    assert restored.allow_local_control is False
    assert restored.speaker_match_threshold == 0.32
    assert restored.performance_mode == "auto"
    assert restored.inference_backend == "auto"
    assert restored.save_event_video_clips is False
    assert restored.save_full_video is False
    assert restored.use_youtube_captions is True
    assert restored.reconnect_enabled is True
    assert restored.reconnect_max_attempts == 8


def test_old_settings_are_migrated_with_video_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    path.write_text(
        '{"schema_version":3,"source_url":"demo://old","hotwords":[]}',
        encoding="utf-8",
    )

    restored = store.load()

    assert restored.schema_version == 12
    assert restored.video_buffer_seconds == 90
    assert restored.save_event_video_clips is False
    assert restored.reconnect_initial_delay_seconds == 5
    assert restored.performance_mode == "auto"
    assert restored.inference_device == "auto"


def test_previous_default_speaker_threshold_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    path.write_text(
        '{"schema_version":7,"speaker_match_threshold":0.42,"hotwords":[]}',
        encoding="utf-8",
    )

    restored = store.load()

    assert restored.schema_version == 12
    assert restored.speaker_match_threshold == 0.32
