from __future__ import annotations

import json
import wave
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from types import SimpleNamespace

import numpy as np
import pytest

from auralwarden.audio import PcmChunk, PcmFormat, PcmRingBuffer
from auralwarden.capture import CaptureConfig, CaptureError, FfmpegPcmCapture, MemoryPcmCapture, ReconnectingCapture, ReconnectConfig
from auralwarden.capture_queue import CaptureQueue
from auralwarden.captions import CaptionCue, CaptionTrack, YoutubeCaptionSource
from auralwarden.clips import AudioClipManager
from auralwarden.diarization.sherpa import SherpaDiarizerConfig, SherpaOnnxDiarizer
from auralwarden.engine import MonitoringEngine
from auralwarden.events import EventBus
from auralwarden import __version__
from auralwarden.hardware import GpuAdapter, HardwareCapabilities, select_inference_plan
from auralwarden.models import AppSettings, DetectionEvent, EventKind, Hotword, SessionState, TranscriptEntry, TranscriptWord
from auralwarden.transcribers.base import ScriptedTranscriber
from auralwarden.video_clips import VideoClipManager, FailedVideoClip


def make_engine(tmp_path, *, transcriber=None, source=None, **options):
    settings = AppSettings(source_url="memory://synthetic", hotwords=[],
                           save_event_audio_clips=False, **options)
    return MonitoringEngine(source or MemoryPcmCapture(1), transcriber or ScriptedTranscriber([]),
                            settings, session_root=tmp_path)


def test_capture_continues_while_inference_waits(tmp_path):
    inference_started = Event()
    second_captured = Event()

    class Source:
        def chunks(self, stop):
            yield PcmChunk(bytes(32000), 0, 1)
            assert inference_started.wait(2)
            second_captured.set()
            yield PcmChunk(bytes(32000), 1, 2)

        def stop(self):
            pass

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            inference_started.set()
            assert second_captured.wait(2), "Capture was blocked by inference"
            return []

    engine = make_engine(tmp_path, source=Source(), transcriber=Transcriber(),
                         transcription_window_seconds=1, transcription_overlap_seconds=0)
    engine.run_foreground()
    assert engine.error is None
    assert engine.state == SessionState.STOPPED


def test_capture_queue_is_bounded_and_reports_discontinuity():
    reader = CaptureQueue(MemoryPcmCapture(5), Event(), PcmFormat(), capacity_seconds=2)
    reader.thread.start()
    reader.thread.join(2)
    assert not reader.thread.is_alive()
    assert reader.queued_seconds == 2
    assert reader.dropped_seconds == 3
    assert reader._items[0].start_seconds == 3


def test_neutral_quality_beats_the_presence_of_a_hotword(tmp_path):
    engine = make_engine(tmp_path)
    engine.update_hotwords([Hotword("clave")])
    original = [TranscriptEntry(0, "Speaker 1", "clave", confidence=0.01,
                                words=[TranscriptWord("clave", 0, 1, 0.01)])]
    refined = [TranscriptEntry(0, "Speaker 1", "seguimos con el ejercicio", confidence=0.99)]
    assert engine._looks_like_guidance_echo(original)
    assert engine._prefer_refined(original, refined, "low_confidence")
    original[0].words[0].probability = 0.99
    assert not engine._looks_like_guidance_echo(original)


def test_adjacent_similar_sentence_keeps_new_hotword(tmp_path):
    engine = make_engine(tmp_path)
    text = "vamos a analizar los resultados de este ejercicio de estadistica"
    engine.transcript.add(TranscriptEntry(0, "Speaker 1", text, end_seconds=5))
    current = TranscriptEntry(5.1, "Speaker 1", text + " ayuda", end_seconds=10)
    assert engine._stabilize_entry(current) is current


def test_late_audio_detection_extracts_only_requested_interval(tmp_path):
    fmt = PcmFormat(sample_rate=10)
    ring = PcmRingBuffer(10, fmt)
    ring.append(bytes(fmt.bytes_for_seconds(6)))
    manager = AudioClipManager(tmp_path, ring, 0, 1)
    detection = DetectionEvent("ayuda", 100, 1, "ayuda", "ayuda")
    clip = manager.schedule(detection, 6)[0]
    with wave.open(str(clip.path), "rb") as audio:
        assert audio.getnframes() == 10
    assert not clip.truncated


def test_missing_audio_preroll_is_reported(tmp_path):
    fmt = PcmFormat(sample_rate=10)
    ring = PcmRingBuffer(30, fmt)
    ring.append(bytes(fmt.bytes_for_seconds(60)))
    clip = AudioClipManager(tmp_path, ring, 60, 0).schedule(
        DetectionEvent("ayuda", 100, 60, "ayuda", "ayuda"), 60
    )[0]
    assert clip.truncated
    with wave.open(str(clip.path), "rb") as audio:
        assert audio.getnframes() == 300


def test_ring_capacity_covers_preroll_and_transcription_window(tmp_path):
    engine = make_engine(tmp_path, audio_buffer_seconds=30, clip_pre_seconds=60,
                         transcription_window_seconds=8)
    assert engine.ring.capacity_seconds >= 68


def test_clip_window_does_not_move_when_fusion_event_changes(tmp_path):
    manifest = tmp_path / "segments.csv"
    manager = VideoClipManager(tmp_path / "out", tmp_path, manifest, 30, 45, 90)
    event = DetectionEvent("ayuda", 100, 10, "ayuda", "ayuda")
    manager.schedule(event, 10)
    event.elapsed_seconds = 50
    pending = manager._pending[event.event_id]
    assert pending.start_seconds == 0
    assert pending.target_end_seconds == 55
    assert pending.detection.elapsed_seconds == 10
    manager.flush()


def test_video_queue_has_a_hard_limit(tmp_path):
    manager = VideoClipManager(tmp_path / "out", tmp_path, tmp_path / "segments.csv",
                               30, 45, 90, max_queued_clips=2)
    for _ in range(2):
        assert manager.schedule(DetectionEvent("ayuda", 100, 10, "ayuda", "ayuda"), 10) == []
    result = manager.schedule(DetectionEvent("ayuda", 100, 10, "ayuda", "ayuda"), 10)
    assert len(manager._pending) == 2
    assert isinstance(result[0], FailedVideoClip)
    manager.flush()


def test_initialization_io_failure_reaches_failed_state(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr("auralwarden.engine.SessionWorkspace", fail)
    engine = make_engine(tmp_path)
    engine.run_foreground()
    assert engine.state == SessionState.FAILED
    assert engine.error == "synthetic disk failure"


def test_diagnostic_io_failure_does_not_hide_primary_error(tmp_path, monkeypatch):
    from auralwarden.session import SessionWorkspace

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            raise RuntimeError("synthetic primary error")

    def fail(*args):
        raise OSError("synthetic log failure")

    monkeypatch.setattr(SessionWorkspace, "write_error_details", fail)
    engine = make_engine(tmp_path, transcriber=Transcriber(), transcription_window_seconds=1,
                         transcription_overlap_seconds=0)
    engine.run_foreground()
    assert engine.state == SessionState.FAILED
    assert engine.error == "synthetic primary error"


def test_manual_stop_preserves_captured_tail(tmp_path):
    class Source:
        def chunks(self, stop):
            engine.stop()
            yield PcmChunk(bytes(64000), 0, 2)
        def stop(self):
            pass
    engine = make_engine(tmp_path, source=Source(),
                         transcriber=ScriptedTranscriber([("Speaker 1", "texto final")]))
    engine.run_foreground()
    assert engine.transcript.entries[0].text == "texto final"


def test_failure_flushes_pending_audio_clip(tmp_path):
    class Source:
        def chunks(self, stop):
            yield PcmChunk(bytes(64000), 0, 2)
            raise CaptureError("synthetic interruption")
        def stop(self):
            pass
    engine = make_engine(tmp_path, source=Source(),
                         transcriber=ScriptedTranscriber([("Speaker 1", "ayuda")]),
                         transcription_window_seconds=2, transcription_overlap_seconds=0,
                         clip_post_seconds=10)
    engine.update_hotwords([Hotword("ayuda")])
    engine.options.save_event_audio_clips = True
    events = []
    engine.events.subscribe(events.append)
    engine.run_foreground()
    clips = [event for event in events if event.kind == EventKind.CLIP]
    assert engine.state == SessionState.FAILED
    assert len(clips) == 1 and clips[0].payload["truncated"]


def test_live_removal_cancels_an_already_computed_match(tmp_path):
    engine = make_engine(tmp_path, source=MemoryPcmCapture(2),
                         transcriber=ScriptedTranscriber([("Speaker 1", "ayuda")]),
                         transcription_window_seconds=2, transcription_overlap_seconds=0)
    engine.update_hotwords([Hotword("ayuda")])
    events = []
    def receive(event):
        events.append(event)
        if event.kind == EventKind.TRANSCRIPT:
            engine.update_hotwords([])
    engine.events.subscribe(receive)
    engine.run_foreground()
    assert not any(event.kind == EventKind.HOTWORD for event in events)


def test_speaker_rename_updates_future_segments(tmp_path):
    engine = make_engine(tmp_path, source=MemoryPcmCapture(2),
                         transcriber=ScriptedTranscriber([("Speaker 1", "primero"),
                                                          ("Speaker 1", "segundo")]),
                         transcription_window_seconds=1, transcription_overlap_seconds=0)
    def receive(event):
        if event.kind == EventKind.TRANSCRIPT and len(engine.transcript.entries) == 1:
            engine.rename_speaker("Speaker 1", "Persona Alfa")
    engine.events.subscribe(receive)
    engine.run_foreground()
    assert [item.speaker_id for item in engine.transcript.entries] == ["Persona Alfa"] * 2


def test_named_phrase_is_not_assembled_across_speakers(tmp_path):
    engine = make_engine(tmp_path, source=MemoryPcmCapture(2),
                         transcriber=ScriptedTranscriber([("Persona Alfa", "palabra"),
                                                          ("Persona Beta", "clave")]),
                         transcription_window_seconds=1, transcription_overlap_seconds=0)
    engine.update_hotwords([Hotword("palabra clave", speaker_profile="Persona Beta")])
    events = []
    engine.events.subscribe(events.append)
    engine.run_foreground()
    assert not any(event.kind == EventKind.HOTWORD for event in events)


def test_unverified_profile_fallback_never_uses_saved_name():
    diarizer = SherpaOnnxDiarizer(SherpaDiarizerConfig("missing", "missing"))
    diarizer._np = np
    vector = np.asarray([1., 0.], dtype=np.float32)
    diarizer._profile_centroids = {"Persona Alfa": vector}
    diarizer._centroids = {"Persona Alfa": vector}
    diarizer._centroid_weights = {"Persona Alfa": 30.0}
    diarizer._embedding_for_turns = lambda *_: np.asarray([0., 1.], dtype=np.float32)
    mapping, _ = diarizer._map_local_speakers([(0, 0, 2)], np.zeros(1), 16000, 10)
    assert mapping[0].startswith("Speaker ")


def test_named_alert_requires_verified_profile_not_renamed_label(tmp_path):
    engine = make_engine(tmp_path, diarization_enabled=True)
    engine.update_hotwords([Hotword("ayuda", speaker_profile="Persona Alfa")])
    match = engine.detector.find_matches("ayuda")[0]
    entry = TranscriptEntry(0, "Persona Alfa", "ayuda", speaker_confidence=0.0)
    assert not engine._match_allowed_for_speaker(match, entry)
    entry.speaker_profile = "Persona Alfa"
    assert engine._match_allowed_for_speaker(match, entry)


def test_historical_captions_are_not_replayed_when_seen_cache_rolls():
    stop = Event()
    polls = 0
    payload = json.dumps({"events": [{"tStartMs": i * 1000, "dDurationMs": 500,
                                       "segs": [{"utf8": f"texto sintetico {i}"}]} for i in range(2001)]}).encode()
    def fetcher(url):
        nonlocal polls
        polls += 1
        if polls == 2:
            stop.set()
        return payload
    source = YoutubeCaptionSource("https://youtube.com/watch?v=synthetic",
                                  resolver=lambda *_: CaptionTrack("https://captions.test", "es", True),
                                  fetcher=fetcher, poll_interval_seconds=0.25)
    assert list(source.cues(stop)) == []


def test_caption_phrase_context_expires_after_pause(tmp_path):
    engine = make_engine(tmp_path)
    engine.update_hotwords([Hotword("palabra clave")])
    manager = AudioClipManager(tmp_path, engine.ring, 0, 0)
    events = []
    engine.events.subscribe(events.append)
    engine._caption_queue.put(CaptionCue("palabra", 1, 2))
    engine._drain_caption_cues(2, manager, None)
    engine._caption_queue.put(CaptionCue("clave", 100, 101))
    engine._drain_caption_cues(101, manager, None)
    assert not any(event.kind == EventKind.HOTWORD for event in events)


def test_caption_clock_conversion_keeps_coherent_clip_timestamp(tmp_path):
    engine = make_engine(tmp_path)
    engine.update_hotwords([Hotword("ayuda")])
    manager = AudioClipManager(tmp_path, engine.ring, 0, 0)
    events = []
    engine.events.subscribe(events.append)
    engine._caption_queue.put(CaptionCue("ayuda", 10, 12))
    engine._drain_caption_cues(3600, manager, None)
    cue = next(event for event in events if event.payload.get("code") == "caption_cue")
    hit = next(event for event in events if event.kind == EventKind.HOTWORD)
    assert cue.payload["elapsed_seconds"] <= cue.payload["end_seconds"] == 3600
    assert hit.payload["elapsed_seconds"] == 3600


def test_nonzero_ffmpeg_exit_without_stderr_is_an_error():
    capture = FfmpegPcmCapture(CaptureConfig("synthetic"))
    capture._ffmpeg = SimpleNamespace(wait=lambda timeout: 9)
    assert "9" in capture._collect_error(False)


@pytest.mark.parametrize("device,acceleration,expected", [
    ("cpu", "auto", "cpu"), ("auto", "vulkan", "vulkan"),
])
def test_explicit_cpp_backend_respects_cpu_and_nvidia_vulkan(tmp_path, device, acceleration, expected):
    model = tmp_path / "synthetic.bin"
    model.write_bytes(b"synthetic")
    caps = HardwareCapabilities(8, 16, 32, (GpuAdapter("Synthetic NVIDIA", "nvidia", 12000),),
                                whisper_cpp_executable="synthetic-vulkan.exe")
    plan = select_inference_plan(caps, backend="whisper_cpp", device=device,
                                  whisper_cpp_model=str(model), whisper_cpp_acceleration=acceleration)
    assert (plan.backend, plan.device) == ("whisper_cpp", expected)


def test_transient_manifest_rewrite_keeps_available_video(tmp_path):
    manifest = tmp_path / "segments.csv"
    (tmp_path / "segment-0.ts").write_bytes(b"synthetic")
    manifest.write_text("segment-0.ts,0,2\n", encoding="utf-8")
    manager = VideoClipManager(tmp_path / "out", tmp_path, manifest, 1, 1, 30)
    try:
        manager._refresh_segments()
        manifest.write_text("", encoding="utf-8")
        manager._refresh_segments()
        assert len(manager._segments) == 1
        manifest.write_text("segment-0.ts,0,2\n", encoding="utf-8")
        manager._refresh_segments()
        assert len(manager._segments) == 1
    finally:
        manager._executor.shutdown()


def test_manifest_can_append_while_reading(tmp_path):
    manifest = tmp_path / "segments.csv"
    manifest.write_bytes(b"original\n")
    with manifest.open("rb") as reader:
        with manifest.open("ab") as writer:
            writer.write(b"updated\n")
        assert reader.read() == b"original\nupdated\n"


def test_cancelled_capture_does_not_launch_ffmpeg(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic")
    capture = FfmpegPcmCapture(CaptureConfig(str(source)))
    capture.stop()
    monkeypatch.setattr("auralwarden.capture.subprocess.Popen",
                        lambda *args, **kwargs: pytest.fail("La captura cancelada inició FFmpeg"))
    assert list(capture.chunks(Event())) == []


def test_full_video_index_is_incremental_and_ram_bounded(tmp_path):
    manifest = tmp_path / "segments-full.csv"
    manager = VideoClipManager(tmp_path / "out", tmp_path, manifest, 1, 1, 5,
                               retain_all_segments=True)
    try:
        for index in range(20):
            name = f"segment-{index}.ts"
            (tmp_path / name).write_bytes(b"synthetic")
            with manifest.open("a", encoding="utf-8") as output:
                output.write(f"{name},{index},{index + 1}\n")
            manager.push(index + 1)
        assert len(manager._segments) <= 8
        assert len(list(tmp_path.glob("segment-*.ts"))) == 20
        offset = manager._manifest_offset
        manager._refresh_segments()
        assert manager._manifest_offset == offset
    finally:
        manager._executor.shutdown()


def test_event_bus_concurrent_publishers_do_not_raise_queue_full():
    bus = EventBus(max_queue_size=1)
    from auralwarden.models import EngineEvent
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: bus.publish(EngineEvent(EventKind.INFO, {"n": i})), range(1000)))
    assert len(bus.drain()) == 1


def test_installed_metadata_matches_release_files():
    assert version("auralwarden") == __version__
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == __version__


def test_m3u8_sequence_restart_does_not_suppress_new_segments():
    playlists = iter([b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:50\nold.vtt\n",
                      b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\nnew.vtt\n"])
    requested = []
    def fetch(url):
        requested.append(url)
        if url.endswith(".m3u8"):
            return next(playlists)
        return b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nsynthetic\n"
    source = YoutubeCaptionSource("https://youtube.com/watch?v=synthetic", fetcher=fetch)
    track = CaptionTrack("https://captions.test/live.m3u8", "es", True, "vtt", "m3u8_native")
    source._fetch_track(track)
    source._seen_segments.add("es|0")
    assert source._fetch_track(track)
    assert "https://captions.test/new.vtt" in requested
