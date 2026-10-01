from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


CURRENT_SETTINGS_SCHEMA = 12


class SessionState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class EventKind(StrEnum):
    STATE = "state"
    TRANSCRIPT = "transcript"
    HOTWORD = "hotword"
    CLIP = "clip"
    RESOURCE = "resource"
    ERROR = "error"
    INFO = "info"


@dataclass(slots=True)
class Hotword:
    phrase: str
    enabled: bool = True
    threshold: int = 88
    speaker_profile: str = ""


@dataclass(slots=True)
class AppSettings:
    schema_version: int = CURRENT_SETTINGS_SCHEMA
    source_url: str = "demo://spanish-news"
    source_kind: str = "url"
    system_audio_device: str = ""
    microphone_device: str = ""
    source_title: str = ""
    preview_mode: str = "synced"
    hotwords: list[Hotword] = field(
        default_factory=lambda: [Hotword("proyecto"), Hotword("alerta")]
    )
    clip_pre_seconds: int = 30
    clip_post_seconds: int = 45
    audio_buffer_seconds: int = 60
    video_buffer_seconds: int = 90
    merge_nearby_seconds: int = 20
    save_full_audio: bool = False
    save_full_video: bool = False
    use_youtube_captions: bool = True
    auto_save_transcript: bool = False
    desktop_notifications: bool = True
    sound_notifications: bool = True
    notification_sound: str = "Default"
    minimize_to_tray: bool = True
    transcript_directory: str = ""
    clips_directory: str = ""
    recordings_directory: str = ""
    speaker_names: dict[str, str] = field(default_factory=dict)
    language: str = "es"
    model_name: str = "auto"
    performance_mode: str = "auto"
    dynamic_load_adaptation: bool = True
    interface_scale_percent: int = 100
    allow_local_control: bool = False
    inference_backend: str = "auto"
    inference_device: str = "auto"
    compute_type: str = "auto"
    whisper_cpp_executable: str = ""
    whisper_cpp_model: str = ""
    whisper_cpp_acceleration: str = "auto"
    transcription_window_seconds: float = 6.0
    transcription_overlap_seconds: float = 2.0
    second_pass_margin: int = 8
    low_confidence_second_pass_threshold: float = 0.62
    rescue_empty_windows: bool = True
    rescue_rms_threshold: float = 0.004
    recognition_context: str = ""
    vocabulary: list[str] = field(default_factory=list)
    diarization_enabled: bool = False
    diarization_segmentation_model: str = ""
    diarization_embedding_model: str = ""
    diarization_num_speakers: int = 0
    diarization_cluster_threshold: float = 0.75
    speaker_match_threshold: float = 0.32
    voice_profile_threshold: float = 0.55
    diarization_threads: int = 2
    save_event_audio_clips: bool = True
    save_event_video_clips: bool = False
    video_stream_quality: str = "720p,480p,best"
    reconnect_enabled: bool = True
    reconnect_max_attempts: int = 8
    reconnect_initial_delay_seconds: int = 5
    reconnect_max_delay_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppSettings":
        known = {field_name for field_name in cls.__dataclass_fields__}
        values = {key: value for key, value in raw.items() if key in known}
        source_schema = int(raw.get("schema_version", 0) or 0)
        values["schema_version"] = CURRENT_SETTINGS_SCHEMA
        if source_schema < 7:
            values.setdefault("performance_mode", "auto")
            values.setdefault("inference_backend", "auto")
        if source_schema < 8:
            previous_threshold = float(
                values.get("speaker_match_threshold", 0.42) or 0.42
            )
            if abs(previous_threshold - 0.42) < 0.0001:
                values["speaker_match_threshold"] = 0.32
        if source_schema < 9:
            values.setdefault("save_full_video", False)
            values.setdefault("use_youtube_captions", True)
        if source_schema < 10:
            values.setdefault("voice_profile_threshold", 0.55)
        if source_schema < 11:
            values.setdefault("dynamic_load_adaptation", True)
            values.setdefault("interface_scale_percent", 100)
        if source_schema < 12:
            values.setdefault("allow_local_control", False)
        values["hotwords"] = [
            item if isinstance(item, Hotword) else Hotword(**item)
            for item in values.get("hotwords", [])
            if isinstance(item, (dict, Hotword))
        ]
        values["vocabulary"] = [
            str(item).strip()
            for item in values.get("vocabulary", [])
            if str(item).strip()
        ]
        return cls(**values)


@dataclass(slots=True)
class TranscriptWord:
    text: str
    start_seconds: float
    end_seconds: float
    probability: float | None = None


@dataclass(slots=True)
class TranscriptEntry:
    elapsed_seconds: float
    speaker_id: str
    text: str
    end_seconds: float | None = None
    created_at: datetime = field(default_factory=datetime.now)
    confirmed: bool = True
    hotwords: list[str] = field(default_factory=list)
    confidence: float | None = None
    source: str = "stt"
    second_pass: bool = False
    refinement_reason: str | None = None
    words: list[TranscriptWord] = field(default_factory=list)
    speaker_confidence: float | None = None
    no_speech_probability: float | None = None
    speaker_profile: str = ""

    def display_timestamp(self) -> str:
        total = max(0, int(self.elapsed_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass(slots=True)
class HotwordMatch:
    phrase: str
    score: float
    matched_text: str
    threshold: int = 88
    exact: bool = False

    @property
    def accepted(self) -> bool:
        return self.score >= self.threshold


@dataclass(slots=True)
class DetectionEvent:
    phrase: str
    score: float
    elapsed_seconds: float
    context: str
    matched_text: str
    speaker_id: str = ""
    event_id: str = field(default_factory=lambda: uuid4().hex)
    first_detected_at: datetime = field(default_factory=datetime.now)
    last_detected_at: datetime = field(default_factory=datetime.now)
    occurrences: int = 1
    second_pass: bool = False


@dataclass(slots=True)
class EngineEvent:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }


@dataclass(slots=True)
class ResourceSnapshot:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    process_memory_mb: float = 0.0
    gpu_percent: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    network_mbps: float = 0.0
