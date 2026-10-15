from __future__ import annotations

import time
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from auralwarden.audio import PcmChunk
from auralwarden.window_video import (
    WindowCaptureError, WindowTarget, WindowVideoRecorder, output_dimensions, validate_target, window_target,
)


def test_window_video_resolution_is_even_and_bounded():
    assert output_dimensions(1920, 1080) == (1280, 720)
    assert output_dimensions(641, 481) == (640, 480)
    assert output_dimensions(500, 1000) == (360, 720)


def test_concat_uses_manifest_durations_instead_of_transport_stream_estimates(tmp_path):
    from auralwarden.video_clips import VideoClipManager, VideoSegment

    manifest = tmp_path / "recording.ffconcat"
    VideoClipManager._write_concat_file(manifest, [
        VideoSegment(tmp_path / "first.ts", 0.064, 2.064),
        VideoSegment(tmp_path / "last.ts", 2.064, 2.464),
    ])
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines[2] == "duration 2.000000"
    assert lines[4] == "duration 0.400000"


@pytest.mark.parametrize("size", [(0, 1080), (1920, 1), (10000, 10000)])
def test_window_video_rejects_invalid_frame_sizes(size):
    with pytest.raises(WindowCaptureError):
        output_dimensions(*size)


@pytest.mark.parametrize("handle", [0, -1, True, "123"])
def test_window_target_requires_a_real_positive_handle(handle):
    with pytest.raises(WindowCaptureError):
        window_target(handle)


def test_window_recorder_has_bounded_audio_queue(tmp_path):
    recorder = WindowVideoRecorder(WindowTarget(123, 1, 1.0, "Synthetic", "test.exe"), tmp_path)
    for index in range(32):
        recorder.feed_audio(PcmChunk(b"\0" * 32000, index, index + 1))
    with pytest.raises(WindowCaptureError, match="búfer"):
        recorder.feed_audio(PcmChunk(b"\0" * 32000, 32, 33))


def test_recycled_window_handle_is_rejected(monkeypatch):
    from auralwarden import window_video

    original = WindowTarget(123, 1, 1.0, "Synthetic", "test.exe")
    replacement = WindowTarget(123, 2, 2.0, "Other", "other.exe")
    monkeypatch.setattr(window_video, "window_target", lambda hwnd: replacement)
    with pytest.raises(WindowCaptureError, match="original"):
        validate_target(original)


def test_window_mode_retains_explicit_audio_and_video_options(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.models import AppSettings
    from auralwarden.settings_store import SettingsStore
    from auralwarden.ui import main_window
    from auralwarden.windows_audio import WindowsAudioDevice

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "list_windows_audio_devices", lambda kind:
                        [WindowsAudioDevice("Synthetic output", "system_audio", True)])
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_url="", source_kind="window_capture",
                           window_capture_hwnd=999, window_capture_pid=99))
    window = main_window.MainWindow(settings_store=store)
    assert window._selected_window_target is None
    assert window.settings.window_capture_hwnd == 0
    assert window.window_pick_button.isHidden() is False
    assert window.quick_settings.save_full_video.isEnabled()
    assert window.quick_settings.save_event_video_clips.isEnabled()
    window._selected_window_target = WindowTarget(123, 1, 1.0, "Synthetic", "test.exe")
    window.quick_settings.save_full_video.setChecked(True)
    window.quick_settings.save_event_video_clips.setChecked(True)
    settings = window._collect_settings()
    assert settings.source_kind == "window_capture"
    assert settings.system_audio_device == "Synthetic output"
    assert settings.window_capture_hwnd == 123
    assert settings.window_capture_pid == 1
    assert settings.window_capture_created_at == 1.0
    assert settings.save_full_video and settings.save_event_video_clips
    window._quitting = True
    window.close()
    app.processEvents()


def test_demo_never_reuses_real_capture_settings(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.models import AppSettings
    from auralwarden.settings_store import SettingsStore
    from auralwarden.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / "real-settings.json")
    store.save(AppSettings(source_kind="microphone", microphone_device="Synthetic microphone",
                           allow_local_control=True, save_full_audio=True, auto_save_transcript=True))
    window = MainWindow(demo=True, settings_store=store)
    assert window.settings.source_kind == "url"
    assert window.settings.source_url.startswith("demo://")
    assert not window.settings.allow_local_control
    assert not window.settings.save_full_audio
    assert not window.settings.save_full_video
    assert not window.settings.auto_save_transcript
    assert not window.settings.sound_notifications
    assert not window.settings.desktop_notifications
    window._quitting = True
    window.close()
    app.processEvents()


def test_recording_dialog_timer_and_stop_save_the_video(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    np = pytest.importorskip("numpy")
    from PySide6.QtWidgets import QApplication
    from auralwarden import window_recording, window_video

    class Capture:
        def __init__(self, **kwargs):
            self.handlers = {}

        def event(self, handler):
            self.handlers[handler.__name__] = handler
            return handler

        def start_free_threaded(self):
            pixels = np.full((240, 320, 4), 120, dtype=np.uint8)
            self.handlers["on_frame_arrived"](
                SimpleNamespace(frame_buffer=pixels, width=320, height=240),
                SimpleNamespace(stop=lambda: None),
            )
            return SimpleNamespace(stop=lambda: self.handlers["on_closed"]())

    class Audio:
        def set_status_callback(self, callback):
            self.callback = callback

        def chunks(self, stop):
            self.callback("connected", {})
            index = 0
            while not stop.wait(1):
                yield PcmChunk(b"\0" * 32000, index, index + 1)
                index += 1

        def stop(self):
            pass

    original_recorder = window_video.WindowVideoRecorder
    monkeypatch.setattr(window_video, "validate_target", lambda target: None)
    monkeypatch.setattr(window_video, "WasapiPcmCapture", lambda *args: Audio())
    monkeypatch.setattr(window_video, "WindowVideoRecorder", lambda target, directory, **kwargs:
                        original_recorder(target, directory, frame_factory=Capture, **kwargs))
    app = QApplication.instance() or QApplication([])
    dialog = window_recording.WindowRecordingDialog(WindowTarget(123, 1, 1.0, "Synthetic", "test.exe"))
    dialog.show()
    deadline = time.monotonic() + 5
    while dialog.time_label.text() == "00:00:00" and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)
    assert dialog.time_label.text() != "00:00:00"
    dialog.stop_recording()
    deadline = time.monotonic() + 15
    while not dialog.done and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)
    assert dialog.done
    assert dialog.output_path and dialog.output_path.is_file()
    assert dialog.stop_button.text() == "Cerrar"
    dialog.close()
    app.processEvents()


def test_synthetic_window_muxes_video_and_audio(tmp_path, monkeypatch):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    from auralwarden import window_video

    supplied = {}

    class Capture:
        def __init__(self, **kwargs):
            supplied.update(kwargs)
            self.handlers = {}

        def event(self, handler):
            self.handlers[handler.__name__] = handler
            return handler

        def start_free_threaded(self):
            pixels = np.zeros((240, 320, 4), dtype=np.uint8)
            pixels[:, :, 1] = 140
            pixels[:, :, 3] = 255
            self.handlers["on_frame_arrived"](
                SimpleNamespace(frame_buffer=pixels, width=320, height=240),
                SimpleNamespace(stop=lambda: None),
            )
            return SimpleNamespace(stop=lambda: self.handlers["on_closed"]())

    monkeypatch.setattr(window_video, "validate_target", lambda target: None)
    recorder = WindowVideoRecorder(
        WindowTarget(123, 1, 1.0, "Synthetic", "test.exe"), tmp_path, frame_factory=Capture,
    )
    recorder.start()
    recorder.begin()
    for index in range(3):
        tone = (np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000) * 2000).astype(np.int16)
        recorder.feed_audio(PcmChunk(tone.tobytes(), index, index + 1))
        time.sleep(1)
    recorder.stop()
    assert recorder.error == ""
    assert supplied["window_hwnd"] == 123
    assert supplied["monitor_index"] is None
    assert supplied["secondary_window"] is None
    assert supplied["draw_border"] is None
    assert recorder.frames_written >= 30
    assert recorder.manifest_path.is_file()
    assert (tmp_path / "segment-000000.ts").is_file()
    with av.open(str(tmp_path / "segment-000000.ts")) as media:
        assert {stream.type for stream in media.streams} == {"audio", "video"}
        assert next(media.decode(video=0)).width == 320


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_window_capture_runs_original_transcription_and_clip_engine(tmp_path, monkeypatch):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    from auralwarden import window_video
    from auralwarden.engine import MonitoringEngine
    from auralwarden.models import AppSettings, EventKind, Hotword, ResourceSnapshot
    from auralwarden.transcribers.base import ScriptedTranscriber

    class Capture:
        def __init__(self, **kwargs):
            self.handlers = {}

        def event(self, handler):
            self.handlers[handler.__name__] = handler
            return handler

        def start_free_threaded(self):
            pixels = np.zeros((240, 320, 4), dtype=np.uint8)
            pixels[:, :, 2:] = 180
            self.handlers["on_frame_arrived"](
                SimpleNamespace(frame_buffer=pixels, width=320, height=240),
                SimpleNamespace(stop=lambda: None),
            )
            return SimpleNamespace(stop=lambda: self.handlers["on_closed"]())

    class Audio:
        def set_status_callback(self, callback):
            self.callback = callback

        def chunks(self, stop):
            self.callback("connected", {})
            for index in range(4):
                tone = (np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000) * 2000).astype(np.int16)
                time.sleep(1)
                yield PcmChunk(tone.tobytes(), index, index + 1)

        def stop(self):
            pass

    original_recorder = window_video.WindowVideoRecorder
    monkeypatch.setattr(window_video, "validate_target", lambda target: None)
    monkeypatch.setattr(window_video, "WasapiPcmCapture", lambda *args: Audio())
    monkeypatch.setattr(window_video, "WindowVideoRecorder", lambda target, directory, **kwargs:
                        original_recorder(target, directory, frame_factory=Capture, **kwargs))
    settings = AppSettings(source_kind="window_capture", source_url="", window_capture_hwnd=123,
                           save_full_video=True, save_event_video_clips=True, save_event_audio_clips=True,
                           hotwords=[Hotword("ayuda")], clip_pre_seconds=0.5, clip_post_seconds=0.5,
                           transcription_window_seconds=1, transcription_overlap_seconds=0)
    source = window_video.WindowPcmCapture(WindowTarget(123, 1, 1.0, "Synthetic", "test.exe"))
    engine = MonitoringEngine(source, ScriptedTranscriber([
        ("Speaker 1", "necesitamos ayuda con el problema"),
        ("Speaker 1", "continuamos con la explicación"),
        ("Speaker 1", "revisamos otro ejemplo"),
        ("Speaker 1", "terminamos este ejercicio"),
    ]), settings, session_root=tmp_path / "sessions")
    engine._resource_sampler = SimpleNamespace(sample=lambda: ResourceSnapshot())
    events = []
    engine.events.subscribe(events.append)
    engine.run_foreground()
    assert engine.error is None
    assert any(event.kind == EventKind.TRANSCRIPT for event in events)
    assert any(event.kind == EventKind.HOTWORD for event in events)
    clips = [Path(event.payload["path"]) for event in events if event.kind == EventKind.CLIP]
    assert any(path.suffix == ".mp4" for path in clips)
    assert any(path.suffix == ".wav" for path in clips)
    with av.open(str(engine.session.full_video_path)) as media:
        assert {stream.type for stream in media.streams} == {"video", "audio"}
