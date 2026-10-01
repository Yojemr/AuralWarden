import wave
import json
import shutil
import subprocess
from pathlib import Path

from auralwarden.audio import PcmFormat
import pytest

from auralwarden.capture import CaptureConfig, FfmpegPcmCapture, MemoryPcmCapture
from auralwarden.engine import MonitoringEngine
from auralwarden.events import EventBus
from auralwarden.models import AppSettings, EventKind, Hotword, ResourceSnapshot, SessionState, TranscriptEntry, TranscriptWord
from auralwarden.transcribers.base import ScriptedTranscriber
from test_capture import create_test_video


class StaticResourceSampler:
    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(cpu_percent=20, memory_percent=30, gpu_percent=40)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_video_clips_resume_after_switch_is_disabled_and_enabled(tmp_path):
    source = tmp_path / "source.mp4"
    create_test_video(source, 12)
    settings = AppSettings(
        source_url=str(source), hotwords=[Hotword("ayuda")],
        save_event_video_clips=True, save_event_audio_clips=False,
        clip_pre_seconds=0.5, clip_post_seconds=0.5,
        transcription_window_seconds=2, transcription_overlap_seconds=0,
    )
    observed = []
    engine = MonitoringEngine(
        FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.5)),
        ScriptedTranscriber([("Speaker 1", text) for text in (
            "necesitamos ayuda para resolver el primer problema",
            "pido ayuda ahora sobre una consulta diferente",
            "esta parte de la explicación necesita ayuda adicional",
            "ayuda con la instalación del programa por favor",
            "hemos completado la actividad de hoy",
            "muchas gracias por participar en esta conversación",
        )]),
        settings, session_root=tmp_path / "sessions",
    )
    engine._resource_sampler = StaticResourceSampler()
    def on_event(event):
        observed.append(event)
        if event.kind == EventKind.TRANSCRIPT:
            count = sum(item.kind == EventKind.TRANSCRIPT for item in observed)
            if count == 1:
                engine.update_clip_preferences(False, False)
            elif count == 3:
                engine.update_clip_preferences(False, True)
    engine.events.subscribe(on_event)
    engine.run_foreground()
    clips = [item for item in observed if item.kind == EventKind.CLIP]
    assert engine.error is None
    assert len(clips) == 2, [(item.kind.value, item.payload) for item in observed
                            if item.kind in {EventKind.INFO, EventKind.ERROR}]
    assert all(Path(item.payload["path"]).stat().st_size > 0 for item in clips)


def test_capture_settings_are_a_session_snapshot(tmp_path):
    settings = AppSettings(save_event_video_clips=False)
    engine = MonitoringEngine(MemoryPcmCapture(1), ScriptedTranscriber([]), settings, session_root=tmp_path)
    settings.save_event_video_clips = True
    assert not engine.settings.save_event_video_clips
    with pytest.raises(ValueError):
        engine.update_clip_preferences(False, True)


class RefiningTranscriber:
    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]:
        text = "Se publicó el contrato" if high_precision else "Se publicó el contato"
        return [
            TranscriptEntry(
                offset_seconds,
                "Speaker 1",
                text,
                end_seconds=offset_seconds + pcm_format.seconds_for_bytes(len(pcm)),
            )
        ]


class LowConfidenceTranscriber:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]:
        self.calls.append(high_precision)
        return [
            TranscriptEntry(
                offset_seconds,
                "Speaker 1",
                "texto recuperado" if high_precision else "texto dudoso",
                end_seconds=offset_seconds + 2,
                confidence=0.9 if high_precision else 0.4,
            )
        ]


class HotwordAwareTranscriber:
    def __init__(self) -> None:
        self.hotwords = ["ayuda"]

    def update_hotwords(self, hotwords: list[str]) -> None:
        self.hotwords = list(hotwords)

    def transcribe(self, *args, **kwargs) -> list[TranscriptEntry]:
        return []


class GuidanceEchoTranscriber:
    def __init__(self) -> None:
        self.verifications = 0

    def transcribe(self, pcm, pcm_format, offset_seconds, *, high_precision=False):
        return [
            TranscriptEntry(
                offset_seconds,
                "Speaker 1",
                "Persona Alfa Persona Beta Taller de pruebas",
                end_seconds=offset_seconds + 2,
                confidence=0.02,
                words=[
                    TranscriptWord("Persona", offset_seconds, offset_seconds + 0.2, 0.001),
                    TranscriptWord("Alfa", offset_seconds + 0.2, offset_seconds + 0.4, 0.001),
                    TranscriptWord("Persona", offset_seconds + 0.4, offset_seconds + 0.6, 0.001),
                    TranscriptWord("Beta", offset_seconds + 0.6, offset_seconds + 0.8, 0.001),
                    TranscriptWord("Taller", offset_seconds + 0.8, offset_seconds + 1.0, 0.001),
                    TranscriptWord("de", offset_seconds + 1.0, offset_seconds + 1.2, 0.001),
                    TranscriptWord("pruebas", offset_seconds + 1.2, offset_seconds + 1.4, 0.001),
                ],
            )
        ]

    def transcribe_verification(self, pcm, pcm_format, offset_seconds):
        self.verifications += 1
        return []


class SilenceHallucinationTranscriber:
    def __init__(self) -> None:
        self.verifications = 0

    def transcribe(self, pcm, pcm_format, offset_seconds, *, high_precision=False):
        return [
            TranscriptEntry(
                offset_seconds,
                "Speaker 1",
                "Gracias por ver el video",
                end_seconds=offset_seconds + 2,
                confidence=0.2,
                no_speech_probability=0.95,
            )
        ]

    def transcribe_verification(self, pcm, pcm_format, offset_seconds):
        self.verifications += 1
        return []


class FailingTranscriber:
    def transcribe(self, *args, **kwargs):
        raise RuntimeError("fallo controlado")


def test_engine_creates_detection_clip_and_transcript(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://test",
        source_title="Boletín de prueba",
        hotwords=[Hotword("licitación")],
        video_buffer_seconds=30,
        audio_buffer_seconds=30,
        clip_pre_seconds=1,
        clip_post_seconds=1,
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        auto_save_transcript=True,
        save_full_audio=True,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        MemoryPcmCapture(6),
        ScriptedTranscriber(
            [
                ("Speaker 1", "Introducción"),
                ("Speaker 2", "La licitación está abierta"),
                ("Speaker 1", "Cierre"),
            ]
        ),
        settings,
        session_root=tmp_path,
        event_bus=bus,
    )
    engine._resource_sampler = StaticResourceSampler()
    engine.run_foreground()

    assert engine.state == SessionState.STOPPED
    assert len(engine.transcript.entries) == 3
    hotword_events = [event for event in observed if event.kind == EventKind.HOTWORD]
    clip_events = [event for event in observed if event.kind == EventKind.CLIP]
    assert len(hotword_events) == 1
    assert len(clip_events) == 1
    clip = Path(clip_events[0].payload["path"])
    assert clip.exists()
    assert clip.parent.name == "audio"
    assert "Clip de audio" in clip.name
    assert "licitación" in clip.name
    with wave.open(str(clip), "rb") as audio:
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 32_000
    assert engine.session is not None
    assert "Boletín de prueba" in engine.session.path.name
    assert engine.session.recording_path.exists()
    assert "Audio completo" in engine.session.recording_path.name
    assert engine.session.transcript_text_path.exists()
    assert "Transcripcion" in engine.session.transcript_text_path.name


def test_hotword_alert_can_be_limited_to_one_identified_speaker(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://speaker-filter",
        hotwords=[Hotword("ayuda", speaker_profile="Ana")],
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        save_event_audio_clips=False,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        MemoryPcmCapture(4),
        ScriptedTranscriber(
            [("Carlos", "Necesito ayuda"), ("Ana", "Ahora necesito ayuda urgente")]
        ),
        settings,
        session_root=tmp_path,
        event_bus=bus,
    )

    engine.run_foreground()

    alerts = [event for event in observed if event.kind == EventKind.HOTWORD]
    assert len(alerts) == 1
    assert alerts[0].payload["speaker_id"] == "Ana"


def test_engine_detects_phrase_split_between_transcript_entries(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://split-hotword",
        hotwords=[Hotword("palabra clave")],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
        clip_pre_seconds=1,
        clip_post_seconds=0,
        transcription_window_seconds=1,
        transcription_overlap_seconds=0,
        save_event_audio_clips=True,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        MemoryPcmCapture(3),
        ScriptedTranscriber(
            [
                ("Speaker 1", "Esta es la palabra"),
                ("Speaker 1", "clave que buscamos"),
                ("Speaker 1", "Continuamos"),
            ]
        ),
        settings,
        session_root=tmp_path,
        event_bus=bus,
    )
    engine._resource_sampler = StaticResourceSampler()

    engine.run_foreground()

    hotword_events = [event for event in observed if event.kind == EventKind.HOTWORD]
    clip_events = [event for event in observed if event.kind == EventKind.CLIP]
    assert len(hotword_events) == 1
    assert hotword_events[0].payload["phrase"] == "palabra clave"
    assert hotword_events[0].payload["matched_text"] == "palabra clave"
    assert "Esta es la palabra clave que buscamos" in hotword_events[0].payload["context"]
    assert len(clip_events) == 1
    assert engine.transcript.entries[0].text == "Esta es la palabra"
    assert engine.transcript.entries[1].text == "clave que buscamos"
    assert engine.transcript.entries[1].hotwords == ["palabra clave"]


def test_engine_does_not_join_fragments_after_a_long_pause(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://split-hotword-gap",
        hotwords=[Hotword("palabra clave")],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
    )
    engine = MonitoringEngine(
        MemoryPcmCapture(1), ScriptedTranscriber([]), settings, session_root=tmp_path
    )
    engine.transcript.add(
        TranscriptEntry(0, "Speaker 1", "palabra", end_seconds=1)
    )

    context = engine._hotword_context_before(
        TranscriptEntry(10, "Speaker 1", "clave", end_seconds=11)
    )

    assert context == ""


def test_engine_stops_detecting_a_hotword_after_live_removal(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://live-hotwords",
        hotwords=[Hotword("ayuda")],
        audio_buffer_seconds=30,
    )
    transcriber = HotwordAwareTranscriber()
    engine = MonitoringEngine(
        MemoryPcmCapture(1), transcriber, settings, session_root=tmp_path
    )

    assert engine.detector.find_matches("Necesito ayuda")

    engine.update_hotwords([])

    assert engine.detector.find_matches("Necesito ayuda") == []
    assert engine.settings.hotwords == []
    assert transcriber.hotwords == []


def test_guidance_echo_is_rechecked_without_guidance_and_discarded(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://guidance-echo",
        hotwords=[Hotword("Persona Alfa"), Hotword("Persona Beta")],
        recognition_context="Taller de pruebas con datos sinteticos",
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        save_event_audio_clips=False,
    )
    observed = []
    transcriber = GuidanceEchoTranscriber()
    engine = MonitoringEngine(
        MemoryPcmCapture(2), transcriber, settings, session_root=tmp_path
    )
    engine.events.subscribe(observed.append)
    engine._resource_sampler = StaticResourceSampler()

    engine.run_foreground()

    assert transcriber.verifications == 1
    assert engine.transcript.entries == []
    assert not any(event.kind == EventKind.HOTWORD for event in observed)


def test_silence_hallucination_is_not_published_when_verification_is_empty(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        source_url="memory://silence",
        hotwords=[],
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        save_event_audio_clips=False,
    )
    transcriber = SilenceHallucinationTranscriber()
    engine = MonitoringEngine(
        MemoryPcmCapture(2), transcriber, settings, session_root=tmp_path
    )
    engine._resource_sampler = StaticResourceSampler()

    engine.run_foreground()

    assert transcriber.verifications == 1
    assert engine.transcript.entries == []


def test_failed_engine_writes_local_traceback_for_diagnosis(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://failure",
        hotwords=[],
        transcription_window_seconds=1,
        transcription_overlap_seconds=0,
    )
    engine = MonitoringEngine(
        MemoryPcmCapture(1), FailingTranscriber(), settings, session_root=tmp_path
    )

    engine.run_foreground()

    assert engine.state == SessionState.FAILED
    assert engine.session is not None
    details = engine.session.error_details_path.read_text(encoding="utf-8")
    assert "RuntimeError: fallo controlado" in details


def test_engine_uses_second_pass_for_doubtful_match(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://refine",
        hotwords=[Hotword("contrato", threshold=96)],
        video_buffer_seconds=30,
        audio_buffer_seconds=30,
        clip_pre_seconds=0,
        clip_post_seconds=0,
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        second_pass_margin=12,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        MemoryPcmCapture(2),
        RefiningTranscriber(),
        settings,
        session_root=tmp_path,
        event_bus=bus,
    )
    engine._resource_sampler = StaticResourceSampler()
    engine.run_foreground()

    assert engine.transcript.entries[0].second_pass is True
    assert any(event.kind == EventKind.HOTWORD for event in observed)


def test_engine_uses_second_pass_for_low_confidence(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://confidence",
        hotwords=[],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        low_confidence_second_pass_threshold=0.62,
    )
    transcriber = LowConfidenceTranscriber()
    engine = MonitoringEngine(
        MemoryPcmCapture(2), transcriber, settings, session_root=tmp_path
    )
    engine._resource_sampler = StaticResourceSampler()
    engine.run_foreground()

    assert transcriber.calls == [False, True]
    assert engine.transcript.entries[0].text == "texto recuperado"
    assert engine.transcript.entries[0].second_pass is True
    assert engine.transcript.entries[0].refinement_reason == "low_confidence"


def test_engine_rescues_non_silent_empty_window(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://rescue",
        hotwords=[],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
        rescue_empty_windows=True,
        rescue_rms_threshold=0.004,
    )
    engine = MonitoringEngine(
        MemoryPcmCapture(1), ScriptedTranscriber([]), settings, session_root=tmp_path
    )
    reason = engine._second_pass_reason([], b"\xe8\x03" * 16_000)
    assert reason == "speech_without_transcript"


def test_engine_trims_confirmed_overlap_prefix(tmp_path: Path) -> None:
    settings = AppSettings(
        source_url="memory://overlap",
        hotwords=[],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
    )
    engine = MonitoringEngine(
        MemoryPcmCapture(1), ScriptedTranscriber([]), settings, session_root=tmp_path
    )
    previous = TranscriptEntry(
        0,
        "Speaker 1",
        "Hola mundo otra vez",
        end_seconds=2,
        words=[
            TranscriptWord(" Hola", 0, 0.5),
            TranscriptWord(" mundo", 0.5, 1),
            TranscriptWord(" otra", 1, 1.5),
            TranscriptWord(" vez", 1.5, 2),
        ],
    )
    current = TranscriptEntry(
        1,
        "Speaker 1",
        "otra vez continuamos aquí",
        end_seconds=3,
        words=[
            TranscriptWord(" otra", 1, 1.5),
            TranscriptWord(" vez", 1.5, 2),
            TranscriptWord(" continuamos", 2, 2.5),
            TranscriptWord(" aquí", 2.5, 3),
        ],
    )
    engine.transcript.add(previous)

    stabilized = engine._stabilize_entry(current)

    assert stabilized is not None
    assert stabilized.text == "continuamos aquí"
    assert stabilized.elapsed_seconds == 2


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required",
)
def test_engine_creates_mp4_clip_with_video_and_audio(tmp_path: Path, monkeypatch) -> None:
    from auralwarden.video_clips import VideoClipManager
    intervals = []
    manifests = []
    original_render = VideoClipManager._render_pending
    original_cleanup = VideoClipManager.cleanup
    def cleanup(manager):
        manifests.append((manager.manifest_path.read_text(encoding="utf-8"),
                          [(path.name, path.stat().st_size) for path in manager.buffer_dir.glob("segment-*.ts")]))
        original_cleanup(manager)
    def render(manager, pending, segments, truncated):
        intervals.append((pending.start_seconds, pending.target_end_seconds,
                          [(item.start_seconds, item.end_seconds) for item in segments], truncated))
        return original_render(manager, pending, segments, truncated)
    monkeypatch.setattr(VideoClipManager, "_render_pending", render)
    monkeypatch.setattr(VideoClipManager, "cleanup", cleanup)
    source = tmp_path / "source.mp4"
    create_test_video(source, 8)
    settings = AppSettings(
        source_url=str(source),
        hotwords=[Hotword("ayuda")],
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
        clip_pre_seconds=1,
        clip_post_seconds=1,
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        save_event_audio_clips=False,
        save_event_video_clips=True,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.5)),
        ScriptedTranscriber(
            [
                ("Speaker 1", "Necesitamos ayuda"),
                ("Speaker 1", "Continuamos"),
                ("Speaker 1", "Cierre"),
                ("Speaker 1", "Fin"),
            ]
        ),
        settings,
        session_root=tmp_path / "sessions",
        event_bus=bus,
    )
    engine._resource_sampler = StaticResourceSampler()

    engine.run_foreground()

    assert engine.state == SessionState.STOPPED
    clip_events = [
        event
        for event in observed
        if event.kind == EventKind.CLIP and event.payload.get("media_type") == "video/mp4"
    ]
    assert len(clip_events) == 1
    clip = Path(clip_events[0].payload["path"])
    assert clip.is_file() and clip.stat().st_size > 0
    assert clip.parent.name == "video"
    assert "Clip de video" in clip.name
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "json",
            str(clip),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    stream_types = {item["codec_type"] for item in json.loads(probe.stdout)["streams"]}
    assert stream_types == {"audio", "video"}
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert 1.5 <= duration <= 3.0, (intervals, manifests, clip_events[0].payload)
    assert engine.session is not None
    assert not engine.session.video_buffer_dir.exists()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required",
)
def test_engine_saves_complete_video_without_event_clips(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    create_test_video(source, 4)
    settings = AppSettings(
        source_url=str(source),
        hotwords=[],
        audio_buffer_seconds=30,
        transcription_window_seconds=2,
        transcription_overlap_seconds=0,
        save_event_audio_clips=False,
        save_event_video_clips=False,
        save_full_video=True,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.5)),
        ScriptedTranscriber([("Speaker 1", "Inicio"), ("Speaker 1", "Final")]),
        settings,
        session_root=tmp_path / "sessions",
        event_bus=bus,
    )
    engine._resource_sampler = StaticResourceSampler()

    engine.run_foreground()

    assert engine.state == SessionState.STOPPED
    assert engine.session is not None
    recording = engine.session.full_video_path
    assert recording.is_file() and recording.stat().st_size > 0
    assert not engine.session.video_buffer_dir.exists()
    assert any(
        event.kind == EventKind.INFO
        and event.payload.get("code") == "full_video_saved"
        for event in observed
    )
