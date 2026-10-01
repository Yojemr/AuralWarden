from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from auralwarden.backends.demo import create_demo_transcriber
from auralwarden.capture import (
    CaptureConfig,
    FfmpegPcmCapture,
    MemoryPcmCapture,
    ReconnectConfig,
    ReconnectingCapture,
    is_remote_source,
)
from auralwarden.captions import YoutubeCaptionSource, is_youtube_source
from auralwarden.diarization import SherpaDiarizerConfig, SherpaOnnxDiarizer
from auralwarden.engine import MonitoringEngine
from auralwarden.events import EventBus
from auralwarden.hardware import detect_hardware, select_inference_plan
from auralwarden.model_catalog import (
    discover_local_whisper_models,
    model_search_roots,
    resolve_local_whisper_model,
)
from auralwarden.models import AppSettings, EngineEvent, EventKind, Hotword
from auralwarden.paths import sessions_dir
from auralwarden.session_recovery import RecoverableTranscript, discard_recovery
from auralwarden.speaker_profiles import SpeakerProfileStore
from auralwarden.transcribers import (
    FasterWhisperConfig,
    FasterWhisperTranscriber,
    WhisperCppConfig,
    WhisperCppTranscriber,
)
from auralwarden.transcript import TranscriptBuffer
from auralwarden.windows_audio import WasapiPcmCapture


class EventRelay(QObject):
    received = Signal(object)

    def forward(self, event: EngineEvent) -> None:
        self.received.emit(event)


def resolve_model_reference(model_name: str) -> str:
    resolved = resolve_local_whisper_model(model_name)
    return str(resolved) if resolved is not None else model_name


def _effective_settings(settings: AppSettings, device: str) -> AppSettings:
    if settings.performance_mode != "low_power":
        return settings
    requires_voice_profiles = any(
        item.enabled and item.speaker_profile.strip() for item in settings.hotwords
    )
    return replace(
        settings,
        transcription_window_seconds=max(8.0, settings.transcription_window_seconds),
        transcription_overlap_seconds=min(1.0, settings.transcription_overlap_seconds),
        low_confidence_second_pass_threshold=0.0,
        rescue_empty_windows=False,
        diarization_enabled=settings.diarization_enabled and requires_voice_profiles,
        inference_device=device,
    )


def _resolve_automatic_model(candidates: tuple[str, ...]) -> str:
    catalog = discover_local_whisper_models()
    for candidate in candidates:
        resolved = resolve_local_whisper_model(candidate, catalog)
        if resolved is not None:
            return str(resolved)
    available = ", ".join(model.name for model in catalog) or "ninguno"
    raise FileNotFoundError(
        "AuralWarden no encontró un modelo local compatible con el equipo. "
        f"Modelos encontrados: {available}. Abra Preferencias > Reconocimiento "
        "para detectar, elegir o instalar un modelo."
    )


def resolve_diarization_models(settings: AppSettings) -> tuple[Path, Path]:
    segmentation = Path(settings.diarization_segmentation_model).expanduser()
    embedding = Path(settings.diarization_embedding_model).expanduser()
    if segmentation.is_file() and embedding.is_file():
        return segmentation.resolve(), embedding.resolve()
    roots = tuple(root / "diarization" for root in model_search_roots())
    for root in roots:
        candidate_segmentation = root / "segmentation.onnx"
        candidate_embedding = root / "embedding.onnx"
        if candidate_segmentation.is_file() and candidate_embedding.is_file():
            return candidate_segmentation.resolve(), candidate_embedding.resolve()
    raise FileNotFoundError(
        "No se encontraron los modelos locales de diarización. "
        "Abra Preferencias > Reconocimiento > Modelos y active la preparación de hablantes."
    )


def build_engine(
    settings: AppSettings,
    bus: EventBus,
    *,
    realtime_demo: bool = True,
) -> MonitoringEngine:
    if settings.source_url.startswith("demo://"):
        return MonitoringEngine(
            MemoryPcmCapture(
                duration_seconds=90,
                chunk_seconds=1,
                realtime=realtime_demo,
            ),
            create_demo_transcriber(),
            settings,
            session_root=sessions_dir(),
            event_bus=bus,
        )

    capabilities = detect_hardware(settings.whisper_cpp_executable)
    plan = select_inference_plan(
        capabilities,
        performance_mode=settings.performance_mode,
        backend=settings.inference_backend,
        device=settings.inference_device,
        compute_type=settings.compute_type,
        model_name=settings.model_name,
        whisper_cpp_model=settings.whisper_cpp_model,
        whisper_cpp_acceleration=settings.whisper_cpp_acceleration,
    )
    effective = _effective_settings(settings, plan.device)
    terms = [item.phrase for item in settings.hotwords if item.enabled]
    if plan.backend == "whisper_cpp":
        transcriber = WhisperCppTranscriber(
            WhisperCppConfig(
                executable=plan.whisper_cpp_executable,
                model=plan.whisper_cpp_model,
                language=settings.language,
                threads=plan.cpu_threads,
                initial_prompt=settings.recognition_context,
                hotwords=terms,
                vocabulary=list(settings.vocabulary),
                use_gpu=plan.device == "vulkan",
            )
        )
    else:
        if settings.model_name == "auto":
            model_reference = _resolve_automatic_model(plan.model_candidates)
        else:
            model_reference = resolve_model_reference(settings.model_name)
            if model_reference == settings.model_name and not Path(model_reference).exists():
                raise FileNotFoundError(
                    f"AuralWarden no encontró un modelo Whisper local para "
                    f"'{settings.model_name}'. Abra Preferencias > Reconocimiento para "
                    "elegir uno de los modelos detectados o indicar su carpeta."
                )
        transcriber = FasterWhisperTranscriber(
            FasterWhisperConfig(
                model_name=model_reference,
                device=plan.device,
                compute_type=plan.compute_type,
                language=settings.language,
                hotwords=terms,
                vocabulary=settings.vocabulary,
                initial_prompt=settings.recognition_context,
                cpu_threads=plan.cpu_threads,
                local_files_only=True,
            )
        )
    diarizer = None
    if effective.diarization_enabled:
        segmentation, embedding = resolve_diarization_models(effective)
        voice_profiles = SpeakerProfileStore().embeddings()
        diarizer = SherpaOnnxDiarizer(
            SherpaDiarizerConfig(
                segmentation_model=str(segmentation),
                embedding_model=str(embedding),
                num_speakers=effective.diarization_num_speakers,
                cluster_threshold=effective.diarization_cluster_threshold,
                speaker_match_threshold=effective.speaker_match_threshold,
                voice_profile_threshold=effective.voice_profile_threshold,
                voice_profiles=voice_profiles,
                num_threads=effective.diarization_threads,
            )
        )
    if settings.source_kind in {"system_audio", "microphone"}:
        if settings.save_event_video_clips or settings.save_full_video:
            raise ValueError(
                "El micrófono y el audio del sistema no admiten grabación de vídeo."
            )
        selected_device = (
            settings.system_audio_device
            if settings.source_kind == "system_audio"
            else settings.microphone_device
        )
        source = WasapiPcmCapture(settings.source_kind, selected_device)
        return MonitoringEngine(
            source,
            transcriber,
            effective,
            session_root=sessions_dir(),
            event_bus=bus,
            diarizer=diarizer,
        )

    capture_quality = (
        settings.video_stream_quality
        if settings.save_event_video_clips or settings.save_full_video
        else "audio_only,best"
    )

    def capture_factory() -> FfmpegPcmCapture:
        return FfmpegPcmCapture(
            CaptureConfig(settings.source_url, quality=capture_quality)
        )

    source = (
        ReconnectingCapture(
            capture_factory,
            ReconnectConfig(
                enabled=settings.reconnect_enabled,
                max_attempts=settings.reconnect_max_attempts,
                initial_delay_seconds=settings.reconnect_initial_delay_seconds,
                max_delay_seconds=settings.reconnect_max_delay_seconds,
            ),
        )
        if is_remote_source(settings.source_url)
        else capture_factory()
    )
    caption_source = (
        YoutubeCaptionSource(
            settings.source_url,
            settings.language,
            status_callback=lambda code, message, details: bus.publish(
                EngineEvent(
                    EventKind.INFO,
                    {"code": code, "message": message, **details},
                )
            ),
        )
        if settings.use_youtube_captions and is_youtube_source(settings.source_url)
        else None
    )
    return MonitoringEngine(
        source,
        transcriber,
        effective,
        session_root=sessions_dir(),
        event_bus=bus,
        diarizer=diarizer,
        caption_source=caption_source,
    )


class MonitoringController(QObject):
    event_received = Signal(object)

    def __init__(
        self,
        engine_builder: Callable[[AppSettings, EventBus], MonitoringEngine] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._builder = engine_builder or build_engine
        self.engine: MonitoringEngine | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._recovered_transcript = TranscriptBuffer()
        self._recovered_session: RecoverableTranscript | None = None
        self.relay = EventRelay(self)
        self.relay.received.connect(self.event_received)

    @property
    def running(self) -> bool:
        return bool(self.engine and (self.engine.running or self.engine.worker_alive))

    def start(self, settings: AppSettings) -> MonitoringEngine:
        if self.running:
            raise RuntimeError("La monitorización ya está activa.")
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        bus = EventBus()
        self._unsubscribe = bus.subscribe(self.relay.forward)
        self.engine = self._builder(settings, bus)
        self._recovered_transcript.clear()
        self._recovered_session = None
        self.engine.start()
        return self.engine

    def stop(self) -> None:
        if self.engine is not None:
            self.engine.stop()

    def update_hotwords(self, hotwords: list[Hotword]) -> None:
        if self.engine is not None and self.engine.running:
            self.engine.update_hotwords(hotwords)

    def update_clip_preferences(self, audio: bool, video: bool) -> None:
        if self.engine is not None and self.engine.running:
            self.engine.update_clip_preferences(audio, video)

    def stop_and_wait(self, timeout: float = 10.0) -> bool:
        if self.engine is None:
            return True
        self.engine.stop()
        self.engine.join(timeout)
        return not self.engine.worker_alive

    def close(self) -> bool:
        if not self.stop_and_wait(0.0):
            return False
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        return True

    def export_transcript(self, path: Path) -> None:
        transcript = self._current_transcript()
        if transcript is None or not transcript.entries:
            raise RuntimeError("No hay una transcripción para guardar.")
        transcript.export_text(path, "AuralWarden")
        if self._recovered_session is not None:
            discard_recovery(self._recovered_session)

    def restore_recovered_transcript(self, recovery: RecoverableTranscript) -> None:
        self.engine = None
        self._recovered_transcript.clear()
        for entry in recovery.entries:
            self._recovered_transcript.add(entry)
        self._recovered_session = recovery

    def discard_recovered_transcript(self) -> None:
        if self._recovered_session is not None:
            discard_recovery(self._recovered_session)
        self._recovered_transcript.clear()
        self._recovered_session = None

    @property
    def transcript_entries(self) -> tuple:
        transcript = self._current_transcript()
        return tuple(transcript.entries) if transcript is not None else ()

    def _current_transcript(self) -> TranscriptBuffer | None:
        if self.engine is not None and self.engine.transcript.entries:
            return self.engine.transcript
        if self._recovered_transcript.entries:
            return self._recovered_transcript
        return None

    def rename_speaker(self, speaker_id: str, display_name: str) -> None:
        if self.engine is not None:
            self.engine.rename_speaker(speaker_id, display_name)
        elif self._recovered_transcript.entries:
            self._recovered_transcript.rename_speaker(speaker_id, display_name)

    def speaker_embedding(self, speaker_id: str) -> list[float] | None:
        if self.engine is None:
            return None
        exporter = getattr(self.engine.diarizer, "export_speaker_embedding", None)
        if not callable(exporter):
            return None
        return exporter(speaker_id)

    @property
    def transcript_dirty(self) -> bool:
        transcript = self._current_transcript()
        return bool(transcript and transcript.dirty)

    @property
    def session_path(self) -> Path | None:
        if self.engine is not None and self.engine.session is not None:
            return self.engine.session.path
        if self._recovered_session is not None:
            return self._recovered_session.session_path
        return None

    @property
    def audio_clips_path(self) -> Path | None:
        if self.engine is None or self.engine.session is None:
            return None
        return self.engine.session.audio_clips_dir

    @property
    def recordings_path(self) -> Path | None:
        session = self.session_path
        return session / "recordings" if session is not None else None

    @property
    def video_clips_path(self) -> Path | None:
        if self.engine is None or self.engine.session is None:
            return None
        return self.engine.session.video_clips_dir

    @property
    def transcripts_path(self) -> Path | None:
        session = self.session_path
        return session / "transcripts" if session is not None else None
