from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from auralwarden.models import AppSettings
from auralwarden.paths import presets_path


PRESET_FIELDS = (
    "hotwords",
    "clip_pre_seconds",
    "clip_post_seconds",
    "audio_buffer_seconds",
    "video_buffer_seconds",
    "merge_nearby_seconds",
    "save_full_audio",
    "save_full_video",
    "use_youtube_captions",
    "auto_save_transcript",
    "desktop_notifications",
    "sound_notifications",
    "notification_sound",
    "minimize_to_tray",
    "language",
    "model_name",
    "performance_mode",
    "dynamic_load_adaptation",
    "interface_scale_percent",
    "inference_backend",
    "inference_device",
    "compute_type",
    "transcription_window_seconds",
    "transcription_overlap_seconds",
    "second_pass_margin",
    "low_confidence_second_pass_threshold",
    "rescue_empty_windows",
    "rescue_rms_threshold",
    "recognition_context",
    "vocabulary",
    "diarization_enabled",
    "diarization_num_speakers",
    "diarization_cluster_threshold",
    "speaker_match_threshold",
    "voice_profile_threshold",
    "diarization_threads",
    "save_event_audio_clips",
    "save_event_video_clips",
    "video_stream_quality",
    "reconnect_enabled",
    "reconnect_max_attempts",
    "reconnect_initial_delay_seconds",
    "reconnect_max_delay_seconds",
)


@dataclass(frozen=True, slots=True)
class ConfigurationPreset:
    name: str
    values: dict[str, Any]
    built_in: bool = False
    updated_at: str = ""


BUILT_IN_PRESETS = (
    ConfigurationPreset(
        "Máxima detección",
        {
            "performance_mode": "precision",
            "dynamic_load_adaptation": True,
            "transcription_window_seconds": 6.0,
            "transcription_overlap_seconds": 2.0,
            "low_confidence_second_pass_threshold": 0.68,
            "rescue_empty_windows": True,
        },
        built_in=True,
    ),
    ConfigurationPreset(
        "Equilibrado",
        {
            "performance_mode": "balanced",
            "dynamic_load_adaptation": True,
            "transcription_window_seconds": 7.0,
            "transcription_overlap_seconds": 1.5,
            "low_confidence_second_pass_threshold": 0.58,
            "rescue_empty_windows": True,
        },
        built_in=True,
    ),
    ConfigurationPreset(
        "Bajo consumo",
        {
            "performance_mode": "low_power",
            "dynamic_load_adaptation": True,
            "transcription_window_seconds": 9.0,
            "transcription_overlap_seconds": 1.0,
            "low_confidence_second_pass_threshold": 0.0,
            "rescue_empty_windows": False,
        },
        built_in=True,
    ),
)


class PresetStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or presets_path()

    def list(self) -> list[ConfigurationPreset]:
        custom = self._load_custom()
        return [*BUILT_IN_PRESETS, *sorted(custom, key=lambda item: item.name.casefold())]

    def save(self, name: str, settings: AppSettings) -> ConfigurationPreset:
        clean_name = " ".join(name.split()).strip()
        if not clean_name:
            raise ValueError("Escribe un nombre para el preset.")
        if any(item.name.casefold() == clean_name.casefold() for item in BUILT_IN_PRESETS):
            raise ValueError("Ese nombre pertenece a un preset incluido.")
        payload = settings.to_dict()
        values = {key: payload[key] for key in PRESET_FIELDS if key in payload}
        preset = ConfigurationPreset(
            clean_name,
            values,
            updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        custom = [
            item
            for item in self._load_custom()
            if item.name.casefold() != clean_name.casefold()
        ]
        custom.append(preset)
        self._write(custom)
        return preset

    def delete(self, name: str) -> bool:
        custom = self._load_custom()
        remaining = [item for item in custom if item.name.casefold() != name.casefold()]
        if len(remaining) == len(custom):
            return False
        self._write(remaining)
        return True

    def apply(self, name: str, current: AppSettings) -> AppSettings:
        preset = next(
            (item for item in self.list() if item.name.casefold() == name.casefold()),
            None,
        )
        if preset is None:
            raise KeyError(name)
        merged = current.to_dict()
        merged.update(preset.values)
        return AppSettings.from_dict(merged)

    def _load_custom(self) -> list[ConfigurationPreset]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        records = payload.get("presets", []) if isinstance(payload, dict) else []
        result: list[ConfigurationPreset] = []
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get("values"), dict):
                continue
            name = " ".join(str(item.get("name") or "").split())
            if not name:
                continue
            result.append(
                ConfigurationPreset(
                    name,
                    {key: value for key, value in item["values"].items() if key in PRESET_FIELDS},
                    updated_at=str(item.get("updated_at") or ""),
                )
            )
        return result

    def _write(self, presets: list[ConfigurationPreset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "presets": [
                        {
                            "name": item.name,
                            "values": item.values,
                            "updated_at": item.updated_at,
                        }
                        for item in presets
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)
