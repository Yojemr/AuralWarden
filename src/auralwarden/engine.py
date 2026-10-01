from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from queue import Empty, Full, Queue
from time import monotonic
from threading import Event, RLock, Thread
from typing import Protocol
import traceback

from auralwarden.audio import PcmFormat, PcmRingBuffer, WaveRecorder, pcm_rms
from auralwarden.captions import CaptionCue, CaptionSource
from auralwarden.capture_queue import CaptureQueue
from auralwarden.clips import AudioClipManager, CompletedAudioClip
from auralwarden.detection import DetectionFusion
from auralwarden.diarization import Diarizer, NullDiarizer
from auralwarden.events import EventBus
from auralwarden.hotwords import HotwordDetector, normalize_text
from auralwarden.models import (
    AppSettings,
    EngineEvent,
    EventKind,
    Hotword,
    HotwordMatch,
    SessionState,
    TranscriptEntry,
)
from auralwarden.paths import sessions_dir
from auralwarden.resources import (
    AdaptiveLoadController,
    LoadProfile,
    ResourceHistory,
    ResourceSampler,
)
from auralwarden.session import SessionWorkspace
from auralwarden.transcribers.base import Transcriber
from auralwarden.transcript import TranscriptBuffer
from auralwarden.video_clips import (
    CompletedVideoClip,
    FailedVideoClip,
    VideoClipManager,
    VideoClipOutcome,
    cleanup_video_buffer,
    render_full_video_recording,
)


class AudioSource(Protocol):
    def chunks(self, stop_event: Event): ...
    def stop(self) -> None: ...


@dataclass(slots=True)
class EngineOptions:
    source_label: str
    source_title: str = ""
    buffer_seconds: float = 60.0
    window_seconds: float = 8.0
    overlap_seconds: float = 1.0
    minimum_final_window_seconds: float = 1.5
    clip_pre_seconds: float = 30.0
    clip_post_seconds: float = 45.0
    merge_nearby_seconds: float = 20.0
    second_pass_margin: int = 8
    low_confidence_second_pass_threshold: float = 0.62
    rescue_empty_windows: bool = True
    rescue_rms_threshold: float = 0.004
    save_full_audio: bool = False
    save_full_video: bool = False
    save_event_audio_clips: bool = True
    save_event_video_clips: bool = False
    video_buffer_seconds: float = 90.0
    auto_save_transcript: bool = False
    resource_interval_seconds: float = 2.0

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "EngineOptions":
        if settings.source_kind == "system_audio":
            source_label = f"system_audio://{settings.system_audio_device or 'predeterminado'}"
        elif settings.source_kind == "microphone":
            source_label = f"microphone://{settings.microphone_device or 'predeterminado'}"
        else:
            source_label = settings.source_url
        return cls(
            source_label=source_label,
            source_title=settings.source_title,
            buffer_seconds=max(30.0, min(120.0, settings.audio_buffer_seconds),
                               settings.clip_pre_seconds + settings.transcription_window_seconds + 5.0),
            window_seconds=settings.transcription_window_seconds,
            overlap_seconds=settings.transcription_overlap_seconds,
            clip_pre_seconds=settings.clip_pre_seconds,
            clip_post_seconds=settings.clip_post_seconds,
            merge_nearby_seconds=settings.merge_nearby_seconds,
            second_pass_margin=settings.second_pass_margin,
            low_confidence_second_pass_threshold=(
                settings.low_confidence_second_pass_threshold
            ),
            rescue_empty_windows=settings.rescue_empty_windows,
            rescue_rms_threshold=settings.rescue_rms_threshold,
            save_full_audio=settings.save_full_audio,
            save_full_video=settings.save_full_video,
            save_event_audio_clips=settings.save_event_audio_clips,
            save_event_video_clips=settings.save_event_video_clips,
            video_buffer_seconds=max(
                settings.clip_pre_seconds + 5.0,
                min(300.0, settings.video_buffer_seconds),
            ),
            auto_save_transcript=settings.auto_save_transcript,
        )

    def validate(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.overlap_seconds < 0 or self.overlap_seconds >= self.window_seconds:
            raise ValueError("overlap_seconds must be between 0 and window_seconds")


class MonitoringEngine:
    HOTWORD_CONTEXT_MAX_GAP_SECONDS = 5.0

    def __init__(
        self,
        source: AudioSource,
        transcriber: Transcriber,
        settings: AppSettings,
        *,
        session_root: Path | None = None,
        pcm_format: PcmFormat | None = None,
        event_bus: EventBus | None = None,
        diarizer: Diarizer | None = None,
        caption_source: CaptionSource | None = None,
    ) -> None:
        self.source = source
        self.transcriber = transcriber
        self.settings = deepcopy(settings)
        self.options = EngineOptions.from_settings(settings)
        self.options.validate()
        self.format = pcm_format or PcmFormat()
        self.events = event_bus or EventBus()
        self.diarizer = diarizer or NullDiarizer()
        self.caption_source = caption_source
        self.transcript = TranscriptBuffer()
        self.ring = PcmRingBuffer(self.options.buffer_seconds, self.format)
        self.detector = HotwordDetector(settings.hotwords)
        self.fusion = DetectionFusion(self.options.merge_nearby_seconds)
        self.session_root = session_root or sessions_dir()
        self.session: SessionWorkspace | None = None
        self.state = SessionState.IDLE
        self.error: str | None = None
        self.resource_history = ResourceHistory(max_samples=60)
        self._resource_sampler = ResourceSampler()
        self._load_controller = AdaptiveLoadController()
        self._stop_event = Event()
        self._caption_stop_event = Event()
        self._caption_queue: Queue[CaptionCue] = Queue(maxsize=256)
        self._caption_thread: Thread | None = None
        self._caption_context = ""
        self._caption_context_end: float | None = None
        self._caption_time_offset: float | None = None
        self._caption_epoch = 0
        self._capture_started_monotonic: float | None = None
        self._thread: Thread | None = None
        self._lock = RLock()
        self._last_resource_sample = -self.options.resource_interval_seconds
        self._last_profile = LoadProfile.NORMAL
        self.video_capture_available = bool(
            self.options.save_event_video_clips or self.options.save_full_video
        )
        self._requested_clips: tuple[bool, bool] | None = None

    def update_clip_preferences(self, audio: bool, video: bool) -> None:
        if video and not self.video_capture_available:
            raise ValueError("Activa la captura de vídeo antes de iniciar esta sesión.")
        with self._lock:
            self._requested_clips = (bool(audio), bool(video))

    def _apply_clip_preferences(self) -> None:
        with self._lock:
            requested = self._requested_clips
            self._requested_clips = None
        if requested is None:
            return
        previous = (self.options.save_event_audio_clips, self.options.save_event_video_clips)
        if requested != previous:
            self.options.save_event_audio_clips, self.options.save_event_video_clips = requested
            # A detection made while saving was paused must not suppress a new clip.
            self.fusion.clear()

    @property
    def running(self) -> bool:
        return self.state in {
            SessionState.STARTING,
            SessionState.RUNNING,
            SessionState.WAITING,
            SessionState.RECONNECTING,
            SessionState.STOPPING,
        }

    def start(self) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("La sesión ya está activa.")
            self._stop_event.clear()
            self._caption_stop_event.clear()
            self._set_state(SessionState.STARTING)
            self._thread = Thread(target=self.run_foreground, name="AuralWardenEngine", daemon=True)
            self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    @property
    def worker_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        if not self.running or self._stop_event.is_set():
            return
        self._set_state(SessionState.STOPPING)
        self._stop_event.set()
        self._caption_stop_event.set()
        Thread(target=self.source.stop, name="AuralWardenStopCapture", daemon=True).start()

    def rename_speaker(self, speaker_key: str, display_name: str) -> None:
        with self._lock:
            previous = self.settings.speaker_names.get(speaker_key, speaker_key)
            self.settings.speaker_names[speaker_key] = display_name
            self.transcript.rename_speaker(previous, display_name)

    def update_hotwords(self, hotwords: list[Hotword]) -> None:
        """Replace the active detection vocabulary without restarting capture."""
        with self._lock:
            updated = list(hotwords)
            self.settings.hotwords = updated
            self.detector.update(updated)
            self.fusion.clear()
            update_transcriber = getattr(self.transcriber, "update_hotwords", None)
            if callable(update_transcriber):
                update_transcriber(
                    [item.phrase for item in updated if item.enabled]
                )

    def run_foreground(self) -> None:
        self.error = None
        if self.state != SessionState.STARTING:
            self._set_state(SessionState.STARTING)
        clip_manager: AudioClipManager | None = None
        video_clip_manager: VideoClipManager | None = None
        video_manifest: Path | None = None
        full_video_saved = False
        recorder: WaveRecorder | None = None
        reader: CaptureQueue | None = None
        pending = bytearray()
        processed_bytes = 0
        last_captured = 0.0
        try:
            self.session = SessionWorkspace(
                self.session_root, self.options.source_label, self.options.source_title
            )
            clip_manager = AudioClipManager(
                self.session.audio_clips_dir, self.ring,
                self.options.clip_pre_seconds, self.options.clip_post_seconds,
            )
            if self.options.save_full_audio:
                recorder = WaveRecorder(self.session.recording_path, self.format)
            set_status_callback = getattr(self.source, "set_status_callback", None)
            if callable(set_status_callback):
                set_status_callback(self._capture_status)
            if self.options.save_event_video_clips or self.options.save_full_video:
                set_retention = getattr(self.source, "set_video_retention", None)
                if callable(set_retention):
                    set_retention(self.options.save_full_video)
                configure_video = getattr(self.source, "configure_video_buffer", None)
                if not callable(configure_video):
                    raise RuntimeError(
                        "La fuente seleccionada no admite grabación de vídeo. "
                        "Use una URL o un archivo de vídeo mediante FFmpeg."
                    )
                video_manifest = configure_video(
                    self.session.video_buffer_dir, segment_seconds=2.0
                )
                if self.video_capture_available:
                    video_clip_manager = VideoClipManager(
                        self.session.video_clips_dir,
                        self.session.video_buffer_dir,
                        video_manifest,
                        self.options.clip_pre_seconds,
                        self.options.clip_post_seconds,
                        self.options.video_buffer_seconds,
                        retain_all_segments=self.options.save_full_video,
                    )
            self.session.update_metadata(status="running")
            self._set_state(SessionState.RUNNING)
            self._start_caption_monitor()
            reader = CaptureQueue(self.source, self._stop_event, self.format,
                                  on_capture=recorder.write if recorder is not None else None)
            last_dropped = 0.0
            for chunk in reader.chunks():
                self._capture_started_monotonic = reader.origin_monotonic
                self._apply_clip_preferences()
                if chunk.start_seconds > last_captured + 0.001:
                    pending.clear()
                    processed_bytes = self.format.bytes_for_seconds(chunk.start_seconds)
                    self.ring.clear()
                    self._caption_context = ""
                    self._caption_context_end = None
                if reader.dropped_seconds > last_dropped or reader.queued_seconds >= 10.0:
                    self.events.publish(EngineEvent(EventKind.INFO, {
                        "code": "capture_backlog",
                        "message": "La transcripción está retrasada respecto al audio capturado.",
                        "queued_seconds": reader.queued_seconds,
                        "dropped_seconds": reader.dropped_seconds,
                    }))
                    last_dropped = reader.dropped_seconds
                last_captured = chunk.end_seconds
                self.ring.append(chunk.data)
                for completed in clip_manager.push(chunk):
                    self._publish_clip(completed)
                if video_clip_manager is not None:
                    self._publish_video_outcomes(
                        video_clip_manager.push(last_captured)
                    )
                self._drain_caption_cues(
                    last_captured, clip_manager, video_clip_manager
                )
                self._sample_resources(last_captured)
                pending.extend(chunk.data)
                processed_bytes = self._process_full_windows(
                    pending,
                    processed_bytes,
                    last_captured,
                    clip_manager,
                    video_clip_manager,
                )

            minimum_bytes = self.format.bytes_for_seconds(
                self.options.minimum_final_window_seconds
            )
            if len(pending) >= minimum_bytes:
                offset = self.format.seconds_for_bytes(processed_bytes)
                self._process_window(
                    bytes(pending),
                    offset,
                    last_captured,
                    clip_manager,
                    video_clip_manager,
                )
            self._caption_stop_event.set()
            self._join_caption_monitor()
            self._drain_caption_cues(last_captured, clip_manager, video_clip_manager)
            for completed in clip_manager.flush():
                self._publish_clip(completed)
            if video_clip_manager is not None:
                self._publish_video_outcomes(video_clip_manager.flush())
            if self.options.save_full_video and video_manifest is not None:
                try:
                    saved_video = render_full_video_recording(
                        video_manifest,
                        self.session.video_buffer_dir,
                        self.session.full_video_path,
                    )
                    full_video_saved = True
                    self.events.publish(
                        EngineEvent(
                            EventKind.INFO,
                            {
                                "code": "full_video_saved",
                                "message": "La grabación completa de vídeo fue guardada.",
                                "path": str(saved_video),
                            },
                        )
                    )
                except Exception as exc:
                    self.events.publish(
                        EngineEvent(
                            EventKind.INFO,
                            {
                                "code": "full_video_failed",
                                "message": (
                                    "No se pudo finalizar el vídeo completo. Los segmentos "
                                    f"temporales se conservaron para recuperación: {exc}"
                                ),
                                "path": str(self.session.video_buffer_dir),
                            },
                        )
                    )
            if self.options.auto_save_transcript and self.transcript.entries:
                self.transcript.export_text(
                    self.session.transcript_text_path, "AuralWarden"
                )
                self.transcript.export_json(
                    self.session.transcript_json_path
                )
            self.session.update_metadata(
                status="stopped",
                ended_at=datetime.now().isoformat(),
                captured_seconds=last_captured,
                transcript_entries=len(self.transcript.entries),
            )
            self.session.clear_transcript_recovery()
        except Exception as exc:
            self.error = str(exc)
            if self.session is not None:
                try:
                    self.session.write_error_details(traceback.format_exc())
                    self.session.update_metadata(
                        status="failed", ended_at=datetime.now().isoformat(), error=self.error,
                    )
                except OSError:
                    pass
            self.events.publish(EngineEvent(EventKind.ERROR, {"message": self.error}))
            self._set_state(SessionState.FAILED)
        finally:
            self._stop_event.set()
            self._caption_stop_event.set()
            self._join_caption_monitor()
            try:
                self.source.stop()
                if reader is not None and reader.thread.is_alive():
                    reader.thread.join(timeout=10.0)
                if recorder is not None:
                    if reader is not None and reader.thread.is_alive():
                        raise RuntimeError("La captura todavía no terminó; la grabación sigue pendiente.")
                    recorder.close()
                if clip_manager is not None:
                    for completed in clip_manager.flush():
                        self._publish_clip(completed)
                if video_clip_manager is not None:
                    self._publish_video_outcomes(video_clip_manager.flush())
            except Exception as exc:
                self.error = self.error or str(exc)
                self.events.publish(EngineEvent(EventKind.ERROR, {"message": str(exc)}))
                self._set_state(SessionState.FAILED)
            if video_manifest is not None and (
                not self.options.save_full_video or full_video_saved
            ) and not self.error and not (
                video_clip_manager is not None and video_clip_manager.recovery_required
            ):
                if video_clip_manager is not None:
                    try:
                        video_clip_manager.cleanup()
                    except OSError as exc:
                        self.events.publish(EngineEvent(EventKind.INFO, {
                            "code": "video_cleanup_deferred", "message": str(exc),
                        }))
                else:
                    try:
                        cleanup_video_buffer(self.session.video_buffer_dir, video_manifest)
                    except OSError as exc:
                        self.events.publish(EngineEvent(EventKind.INFO, {
                            "code": "video_cleanup_deferred", "message": str(exc),
                        }))
            elif video_manifest is not None and self.session is not None:
                self.events.publish(EngineEvent(EventKind.INFO, {
                    "code": "video_recovery_available",
                    "message": "Se conservaron segmentos de vídeo para recuperar los clips pendientes.",
                    "path": str(self.session.video_buffer_dir),
                }))
            if not self.error:
                self._set_state(SessionState.STOPPED)
            elif self.session is not None:
                try:
                    self.session.update_metadata(status="failed", ended_at=datetime.now().isoformat(),
                                                 error=self.error)
                except OSError:
                    pass

    def _process_full_windows(
        self,
        pending: bytearray,
        processed_bytes: int,
        captured_until: float,
        clip_manager: AudioClipManager,
        video_clip_manager: VideoClipManager | None,
    ) -> int:
        window_bytes = self.format.bytes_for_seconds(self.options.window_seconds)
        step_bytes = self.format.bytes_for_seconds(
            self.options.window_seconds - self.options.overlap_seconds
        )
        while len(pending) >= window_bytes:
            window = bytes(pending[:window_bytes])
            offset = self.format.seconds_for_bytes(processed_bytes)
            self._process_window(
                window,
                offset,
                captured_until,
                clip_manager,
                video_clip_manager,
            )
            del pending[:step_bytes]
            processed_bytes += step_bytes
        return processed_bytes

    def _process_window(
        self,
        window: bytes,
        offset: float,
        captured_until: float,
        clip_manager: AudioClipManager,
        video_clip_manager: VideoClipManager | None,
    ) -> None:
        entries = self.transcriber.transcribe(window, self.format, offset)
        refinement_reason = self._second_pass_reason(entries, window)
        if refinement_reason is not None:
            verification = getattr(self.transcriber, "transcribe_verification", None)
            if callable(verification):
                refined = verification(window, self.format, offset)
            else:
                refined = self.transcriber.transcribe(
                    window,
                    self.format,
                    offset,
                    high_precision=True,
                )
            replace_with_verification = refinement_reason in {
                "guidance_echo",
                "possible_silence_hallucination",
            }
            if (
                refinement_reason == "low_confidence"
                and not refined
                and self._window_is_effectively_silent(window)
            ):
                replace_with_verification = True
            if replace_with_verification or self._prefer_refined(
                entries, refined, refinement_reason
            ):
                for entry in refined:
                    entry.second_pass = True
                    entry.refinement_reason = refinement_reason
                entries = refined
        entries = self.diarizer.assign(entries, window, self.format, offset)
        for entry in entries:
            speaker_key = entry.speaker_id
            entry.speaker_id = self.settings.speaker_names.get(
                entry.speaker_id, entry.speaker_id
            )
            entry = self._stabilize_entry(entry)
            if entry is None:
                continue
            previous_context = self._hotword_context_before(entry)
            direct_matches = [
                match
                for match in self.detector.find_matches(entry.text)
                if self._match_allowed_for_speaker(match, entry)
            ]
            matches_by_phrase = {
                normalize_text(match.phrase): match for match in direct_matches
            }
            boundary_contexts: dict[str, str] = {}
            if previous_context:
                for match in self.detector.find_boundary_matches(
                    previous_context, entry.text
                ):
                    if not self._match_allowed_for_speaker(match, entry):
                        continue
                    target = self._hotword_speaker_target(match)
                    if target and not any(
                        normalize_text(candidate.phrase) == normalize_text(match.phrase)
                        for candidate in self.detector.find_boundary_matches(
                            self._hotword_context_before(entry, same_speaker=True), entry.text
                        )
                    ):
                        continue
                    key = normalize_text(match.phrase)
                    if key not in matches_by_phrase:
                        matches_by_phrase[key] = match
                        boundary_contexts[key] = (
                            f"{previous_context} {entry.text}".strip()
                        )
            matches = list(matches_by_phrase.values())
            entry.hotwords = [match.phrase for match in matches]
            self.transcript.add(entry)
            if self.session is not None:
                self.session.append_transcript_entry(entry)
            self.events.publish(
                EngineEvent(
                    EventKind.TRANSCRIPT,
                    {
                        "elapsed_seconds": entry.elapsed_seconds,
                        "end_seconds": entry.end_seconds,
                        "speaker_id": entry.speaker_id,
                        "speaker_key": speaker_key,
                        "text": entry.text,
                        "hotwords": entry.hotwords,
                        "confidence": entry.confidence,
                        "source": entry.source,
                        "second_pass": entry.second_pass,
                        "refinement_reason": entry.refinement_reason,
                        "words": [asdict(word) for word in entry.words],
                        "speaker_confidence": entry.speaker_confidence,
                        "no_speech_probability": entry.no_speech_probability,
                    },
                )
            )
            for match in matches:
                context = boundary_contexts.get(normalize_text(match.phrase))
                detection_entry = replace(entry, text=context) if context else entry
                self._handle_match(
                    match,
                    detection_entry,
                    captured_until,
                    clip_manager,
                    video_clip_manager,
                )

    def _handle_match(
        self,
        match: HotwordMatch,
        entry: TranscriptEntry,
        captured_until: float,
        clip_manager: AudioClipManager,
        video_clip_manager: VideoClipManager | None,
    ) -> None:
        with self._lock:
            active = next((item for item in self.detector.hotwords
                           if item.enabled and normalize_text(item.phrase) == normalize_text(match.phrase)), None)
            if active is None or match.score < active.threshold or not self._match_allowed_for_speaker(match, entry):
                return
            self._dispatch_match(match, entry, captured_until, clip_manager, video_clip_manager)

    def _dispatch_match(self, match, entry, captured_until, clip_manager, video_clip_manager) -> None:
        result = self.fusion.add(match, entry)
        if self.session is not None:
            self.session.append_detection(
                result.event,
                action="created" if result.created else "merged",
            )
        self.events.publish(
            EngineEvent(
                EventKind.HOTWORD,
                {
                    **self._detection_payload(result.event),
                    "created": result.created,
                    "source": entry.source,
                    "audio_clip_requested": self.options.save_event_audio_clips,
                    "video_clip_requested": self.options.save_event_video_clips,
                },
            )
        )
        if result.created and self.options.save_event_audio_clips:
            for completed in clip_manager.schedule(result.event, captured_until):
                self._publish_clip(completed)
        if result.created and self.options.save_event_video_clips and video_clip_manager is not None:
            self._publish_video_outcomes(
                video_clip_manager.schedule(result.event, captured_until)
            )

    def _start_caption_monitor(self) -> None:
        if self.caption_source is None:
            return
        self.events.publish(
            EngineEvent(
                EventKind.INFO,
                {
                    "code": "caption_monitor_started",
                    "message": "Subtítulos de YouTube activados como fuente auxiliar.",
                },
            )
        )

        def monitor() -> None:
            try:
                for cue in self.caption_source.cues(self._caption_stop_event):
                    if self._caption_stop_event.is_set():
                        return
                    try:
                        self._caption_queue.put_nowait(cue)
                    except Full:
                        try:
                            self._caption_queue.get_nowait()
                        except Empty:
                            pass
                        self._caption_queue.put_nowait(cue)
            except Exception as exc:
                self.events.publish(
                    EngineEvent(
                        EventKind.INFO,
                        {
                            "code": "caption_monitor_unavailable",
                            "message": f"Los subtítulos auxiliares no están disponibles: {exc}",
                        },
                    )
                )

        self._caption_thread = Thread(
            target=monitor, name="AuralWardenCaptions", daemon=True
        )
        self._caption_thread.start()

    def _join_caption_monitor(self) -> None:
        thread = self._caption_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.5)
        self._caption_thread = None

    def _drain_caption_cues(
        self,
        captured_until: float,
        clip_manager: AudioClipManager,
        video_clip_manager: VideoClipManager | None,
    ) -> None:
        while True:
            try:
                cue = self._caption_queue.get_nowait()
            except Empty:
                return
            if cue.clock_epoch != self._caption_epoch:
                self._caption_context = ""
                self._caption_context_end = None
                self._caption_time_offset = None
                self._caption_epoch = cue.clock_epoch
            if (cue.clock_origin_seconds is not None
                    and cue.clock_origin_monotonic is not None
                    and self._capture_started_monotonic is not None):
                time_offset = (cue.clock_origin_monotonic - self._capture_started_monotonic
                               - cue.clock_origin_seconds)
            else:
                if self._caption_time_offset is None:
                    self._caption_time_offset = (
                        captured_until - cue.end_seconds
                        if abs(cue.end_seconds - captured_until) > 120.0 else 0.0
                    )
                time_offset = self._caption_time_offset
            elapsed = cue.start_seconds + time_offset
            end = cue.end_seconds + time_offset
            if end < max(0.0, captured_until - 30.0) or elapsed > captured_until + 15.0:
                continue
            elapsed = max(0.0, min(elapsed, captured_until))
            end = max(elapsed, min(end, captured_until))
            if (self._caption_context_end is not None and (
                    elapsed - self._caption_context_end > self.HOTWORD_CONTEXT_MAX_GAP_SECONDS
                    or end < self._caption_context_end - 0.05)):
                self._caption_context = ""
            entry = TranscriptEntry(
                elapsed_seconds=max(0.0, elapsed),
                end_seconds=end,
                speaker_id="Subtítulos",
                text=cue.text,
                source=cue.source,
            )
            self.events.publish(
                EngineEvent(
                    EventKind.INFO,
                    {
                        "code": "caption_cue",
                        "text": cue.text,
                        "elapsed_seconds": entry.elapsed_seconds,
                        "end_seconds": entry.end_seconds,
                        "language": cue.language,
                        "source_start_seconds": cue.start_seconds,
                        "source_end_seconds": cue.end_seconds,
                    },
                )
            )
            matches_by_phrase = {
                normalize_text(match.phrase): match
                for match in self.detector.find_matches(cue.text)
            }
            boundary_context: dict[str, str] = {}
            if self._caption_context:
                for match in self.detector.find_boundary_matches(
                    self._caption_context, cue.text
                ):
                    key = normalize_text(match.phrase)
                    matches_by_phrase.setdefault(key, match)
                    boundary_context[key] = (
                        f"{self._caption_context} {cue.text}".strip()
                    )
            for match in matches_by_phrase.values():
                if not self._match_allowed_for_speaker(match, entry):
                    continue
                context = boundary_context.get(normalize_text(match.phrase))
                self._handle_match(
                    match,
                    replace(entry, text=context) if context else entry,
                    captured_until,
                    clip_manager,
                    video_clip_manager,
                )
            context_words = f"{self._caption_context} {cue.text}".split()
            self._caption_context = " ".join(context_words[-24:])
            self._caption_context_end = end

    def _hotword_context_before(self, entry: TranscriptEntry, *, same_speaker: bool = False) -> str:
        required_words = self.detector.maximum_phrase_words
        if required_words < 2:
            return ""

        context_word_limit = max(12, required_words + 4)
        parts: list[str] = []
        collected_words = 0
        next_start = entry.elapsed_seconds
        for previous in reversed(self.transcript.entries):
            if same_speaker and (
                previous.speaker_id != entry.speaker_id
                or previous.speaker_profile != entry.speaker_profile
            ):
                break
            previous_end = previous.end_seconds or previous.elapsed_seconds
            gap = max(0.0, next_start - previous_end)
            if gap > self.HOTWORD_CONTEXT_MAX_GAP_SECONDS:
                break
            text = " ".join(previous.text.split())
            normalized = normalize_text(text)
            if not text or not normalized:
                continue
            parts.append(text)
            collected_words += len(normalized.split())
            next_start = previous.elapsed_seconds
            if collected_words >= context_word_limit:
                break

        if not parts:
            return ""
        words = " ".join(reversed(parts)).split()
        return " ".join(words[-context_word_limit:])

    def _hotword_speaker_target(self, match: HotwordMatch) -> str:
        key = normalize_text(match.phrase)
        target = next(
            (
                item.speaker_profile.strip()
                for item in self.detector.hotwords
                if item.enabled and normalize_text(item.phrase) == key
            ),
            "",
        )
        return target

    def _match_allowed_for_speaker(self, match: HotwordMatch, entry: TranscriptEntry | str) -> bool:
        target = self._hotword_speaker_target(match)
        if not target:
            return True
        if isinstance(entry, str):
            return not self.settings.diarization_enabled and normalize_text(target) == normalize_text(entry)
        identity = entry.speaker_profile if self.settings.diarization_enabled else entry.speaker_id
        return normalize_text(target) == normalize_text(identity)

    def _second_pass_reason(
        self,
        entries: list[TranscriptEntry],
        window: bytes,
    ) -> str | None:
        if self._looks_like_guidance_echo(entries):
            return "guidance_echo"
        if self._looks_like_silence_hallucination(entries, window):
            return "possible_silence_hallucination"
        candidates = [
            candidate
            for entry in entries
            for candidate in self.detector.find_candidates(
                entry.text, margin=self.options.second_pass_margin
            )
        ]
        if candidates and not any(candidate.accepted for candidate in candidates):
            return "hotword_candidate"
        if self._last_profile == LoadProfile.CRITICAL:
            return None
        threshold = self.options.low_confidence_second_pass_threshold
        if self._last_profile == LoadProfile.CONSTRAINED:
            threshold = min(threshold, 0.52)
        confidences = [
            entry.confidence for entry in entries if entry.confidence is not None
        ]
        if threshold > 0 and confidences and min(confidences) < threshold:
            return "low_confidence"
        if (
            not entries
            and self.options.rescue_empty_windows
            and pcm_rms(window, self.format) >= self.options.rescue_rms_threshold
        ):
            return "speech_without_transcript"
        return None

    def _window_is_effectively_silent(self, window: bytes) -> bool:
        return pcm_rms(window, self.format) < self.options.rescue_rms_threshold

    def _looks_like_silence_hallucination(
        self,
        entries: list[TranscriptEntry],
        window: bytes,
    ) -> bool:
        if not entries or not self._window_is_effectively_silent(window):
            return False
        probabilities = [
            entry.no_speech_probability
            for entry in entries
            if entry.no_speech_probability is not None
        ]
        return bool(probabilities) and min(probabilities) >= 0.60

    def _looks_like_guidance_echo(
        self, entries: list[TranscriptEntry]
    ) -> bool:
        """Detect low-probability text copied from recognition guidance.

        This only requests an independent second pass. It does not blacklist a
        phrase or reject speech merely because it contains a configured term.
        """
        guided_phrases = [
            item.phrase
            for item in self.settings.hotwords
            if item.enabled and item.phrase.strip()
        ]
        guided_phrases.extend(self.settings.vocabulary)
        if self.settings.recognition_context.strip():
            guided_phrases.append(self.settings.recognition_context)

        targets: set[tuple[str, ...]] = set()
        for phrase in guided_phrases:
            tokens = normalize_text(phrase).split()
            for size in range(1, min(6, len(tokens)) + 1):
                targets.update(
                    tuple(tokens[index : index + size])
                    for index in range(len(tokens) - size + 1)
                )
        if not targets:
            return False

        words: list[str] = []
        probabilities: list[float | None] = []
        for entry in entries:
            for word in entry.words:
                tokens = normalize_text(word.text).split()
                words.extend(tokens)
                probabilities.extend([word.probability] * len(tokens))
        if not words:
            return False

        for size in range(min(6, len(words)), 0, -1):
            for index in range(len(words) - size + 1):
                if tuple(words[index : index + size]) not in targets:
                    continue
                confidence = [
                    value
                    for value in probabilities[index : index + size]
                    if value is not None
                ]
                if len(confidence) == size and sum(confidence) / size <= 0.12:
                    return True
        return False

    def _prefer_refined(
        self,
        original: list[TranscriptEntry],
        refined: list[TranscriptEntry],
        reason: str,
    ) -> bool:
        if not refined:
            return False
        if not original:
            return True
        return self._transcript_quality(refined) >= self._transcript_quality(original)

    def _transcript_quality(self, entries: list[TranscriptEntry]) -> float:
        if not entries:
            return 0.0
        confidences = [
            entry.confidence for entry in entries if entry.confidence is not None
        ]
        confidence = sum(confidences) / len(confidences) if confidences else 0.5
        word_probabilities = [word.probability for entry in entries for word in entry.words
                              if word.probability is not None]
        if word_probabilities:
            confidence = (confidence + sum(word_probabilities) / len(word_probabilities)) / 2.0
        tokens = normalize_text(" ".join(entry.text for entry in entries)).split()
        longest_run = 1
        current_run = 1
        for previous, current in zip(tokens, tokens[1:]):
            if previous == current:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 1
        repetition_penalty = max(0, longest_run - 3) * 0.03
        coverage_bonus = min(len(tokens), 40) * 0.002
        return confidence + coverage_bonus - repetition_penalty

    def _best_candidate_score(self, entries: list[TranscriptEntry]) -> float:
        return max(
            (
                candidate.score
                for entry in entries
                for candidate in self.detector.find_candidates(
                    entry.text, margin=self.options.second_pass_margin
                )
            ),
            default=0.0,
        )

    def _stabilize_entry(self, entry: TranscriptEntry) -> TranscriptEntry | None:
        normalized = normalize_text(entry.text)
        for previous in self.transcript.entries[-8:]:
            previous_normalized = normalize_text(previous.text)
            if not self._entries_temporally_related(previous, entry):
                continue
            if previous_normalized == normalized:
                return None
            if (
                len(normalized.split()) >= 2
                and normalized in previous_normalized
            ):
                return None
            similarity = SequenceMatcher(
                None, previous_normalized, normalized
            ).ratio()
            if similarity >= 0.92 and set(normalized.split()) <= set(previous_normalized.split()):
                return None
            trimmed = self._trim_confirmed_prefix(previous, entry)
            if trimmed is None:
                return None
            if trimmed is not entry:
                entry = trimmed
                normalized = normalize_text(entry.text)
        return entry

    def _entries_temporally_related(
        self, previous: TranscriptEntry, current: TranscriptEntry
    ) -> bool:
        previous_end = previous.end_seconds or previous.elapsed_seconds
        current_end = current.end_seconds or current.elapsed_seconds
        return (
            current.elapsed_seconds < previous_end
            and previous.elapsed_seconds < current_end
        )

    @staticmethod
    def _trim_confirmed_prefix(
        previous: TranscriptEntry, current: TranscriptEntry
    ) -> TranscriptEntry | None:
        if not previous.words or not current.words:
            return current
        previous_tokens = [normalize_text(word.text) for word in previous.words]
        current_tokens = [normalize_text(word.text) for word in current.words]
        maximum = min(len(previous_tokens), len(current_tokens))
        overlap = 0
        for size in range(maximum, 1, -1):
            if previous_tokens[-size:] == current_tokens[:size]:
                overlap = size
                break
        if overlap == 0:
            return current
        remaining = current.words[overlap:]
        if not remaining:
            return None
        text = "".join(word.text for word in remaining).strip()
        if not text:
            return None
        return replace(
            current,
            elapsed_seconds=remaining[0].start_seconds,
            text=text,
            words=remaining,
        )

    def _sample_resources(self, elapsed: float) -> None:
        if elapsed - self._last_resource_sample < self.options.resource_interval_seconds:
            return
        self._last_resource_sample = elapsed
        snapshot = self._resource_sampler.sample()
        self.resource_history.add(snapshot)
        profile = (
            self._load_controller.update(snapshot)
            if self.settings.dynamic_load_adaptation
            else LoadProfile.NORMAL
        )
        if profile != self._last_profile:
            setter = getattr(self.transcriber, "set_resource_profile", None)
            if callable(setter):
                setter(profile.value)
            self._last_profile = profile
        self.events.publish(
            EngineEvent(
                EventKind.RESOURCE,
                {
                    **asdict(snapshot),
                    "profile": profile.value,
                    "adaptation_enabled": self.settings.dynamic_load_adaptation,
                    "pressure_percent": self._load_controller.pressure_percent,
                    "pressure_source": self._load_controller.pressure_source,
                },
            )
        )

    def _publish_clip(
        self, completed: CompletedAudioClip | CompletedVideoClip
    ) -> None:
        media_type = (
            "video/mp4" if isinstance(completed, CompletedVideoClip) else "audio/wav"
        )
        self.events.publish(
            EngineEvent(
                EventKind.CLIP,
                {
                    "event_id": completed.event_id,
                    "path": str(completed.path),
                    "truncated": completed.truncated,
                    "media_type": media_type,
                },
            )
        )

    def _publish_video_outcomes(self, outcomes: list[VideoClipOutcome]) -> None:
        for outcome in outcomes:
            if isinstance(outcome, CompletedVideoClip):
                self._publish_clip(outcome)
                continue
            assert isinstance(outcome, FailedVideoClip)
            self.events.publish(
                EngineEvent(
                    EventKind.INFO,
                    {
                        "code": "video_clip_failed",
                        "event_id": outcome.event_id,
                        "message": outcome.message,
                    },
                )
            )

    @staticmethod
    def _detection_payload(event) -> dict[str, object]:
        return {
            "event_id": event.event_id,
            "phrase": event.phrase,
            "score": event.score,
            "elapsed_seconds": event.elapsed_seconds,
            "context": event.context,
            "matched_text": event.matched_text,
            "speaker_id": event.speaker_id,
            "occurrences": event.occurrences,
            "second_pass": event.second_pass,
        }

    def _set_state(self, state: SessionState) -> None:
        self.state = state
        self.events.publish(EngineEvent(EventKind.STATE, {"state": state.value}))

    def _capture_status(self, phase: str, payload: dict[str, object]) -> None:
        state = {
            "waiting": SessionState.WAITING,
            "reconnecting": SessionState.RECONNECTING,
            "connected": SessionState.RUNNING,
        }.get(phase)
        if state is not None and not self._stop_event.is_set():
            self._set_state(state)
        message = str(payload.get("message") or "")
        detail = {"phase": phase, **payload}
        self.events.publish(EngineEvent(EventKind.INFO, detail))
        if self.session is not None:
            self.session.update_metadata(
                capture_phase=phase,
                capture_message=message,
                reconnect_attempt=payload.get("attempt", 0),
            )
