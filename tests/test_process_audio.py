from __future__ import annotations

from queue import Queue
from threading import Event
from types import SimpleNamespace

import pytest

from auralwarden import process_audio
from auralwarden.audio import PcmChunk
from auralwarden.process_audio import ProcessAudioConverter, ProcessPcmCapture, ProcessTarget, validate_process_target
from auralwarden.windows_audio import WindowsAudioError


TARGET = ProcessTarget(123, 10.0, "synthetic.exe")


@pytest.mark.parametrize("pid", [0, -1, True, "123"])
def test_process_target_rejects_invalid_identifiers(pid):
    with pytest.raises(WindowsAudioError):
        validate_process_target(ProcessTarget(pid, 10, "synthetic.exe"))


@pytest.mark.parametrize("created,exe,running", [(11, "synthetic.exe", True),
                                                 (10, "other.exe", True),
                                                 (10, "synthetic.exe", False)])
def test_process_target_rejects_reuse_without_switching_source(monkeypatch, created, exe, running):
    monkeypatch.setattr(process_audio.psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: created, exe=lambda: exe, is_running=lambda: running))
    with pytest.raises(WindowsAudioError, match="original"):
        validate_process_target(TARGET)


def test_process_identity_accepts_case_insensitive_executable(monkeypatch):
    monkeypatch.setattr(process_audio.psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: 10, exe=lambda: "SYNTHETIC.EXE", is_running=lambda: True))
    validate_process_target(TARGET)


def test_process_converter_preserves_duration_across_irregular_packets():
    np = pytest.importorskip("numpy")
    pytest.importorskip("av")
    samples = (np.sin(np.arange(44100 * 3) * 2 * np.pi * 550 / 44100) * 5000).astype(np.int16)
    raw = np.repeat(samples[:, None], 2, axis=1).tobytes()
    converter = ProcessAudioConverter()
    pieces = [converter.convert(raw[offset:offset + 441 * 4])
              for offset in range(0, len(raw), 441 * 4)]
    output = b"".join(pieces) + converter.flush()
    assert len(output) == 16000 * 3 * 2
    converted = np.frombuffer(output, dtype=np.int16)
    frequencies = np.fft.rfftfreq(len(converted), 1 / 16000)
    assert frequencies[np.abs(np.fft.rfft(converted)).argmax()] == pytest.approx(550)


def test_process_converter_silence_is_silence():
    pytest.importorskip("av")
    converter = ProcessAudioConverter()
    result = converter.convert(bytes(44100 * 4)) + converter.flush()
    assert result == bytes(32000)
    with pytest.raises(WindowsAudioError):
        converter.convert(b"123")


class Channel(Queue):
    def cancel_join_thread(self):
        pass


@pytest.mark.parametrize("has_audio", [False, True])
def test_worker_converts_or_emits_silence_and_closes_native(monkeypatch, has_audio):
    pytest.importorskip("av")
    from auralwarden import _process_audio_native

    stop = Event()
    packets, errors = Channel(maxsize=16), Channel(maxsize=1)
    ticks = [0.0]
    closed = []

    class Reader:
        def __init__(self, pid, stop):
            assert pid == 123

        def read(self):
            ticks[0] += 0.1
            if ticks[0] >= 3.1:
                stop.set()
            return b"\x10\0\x10\0" * 4410 if has_audio else b""

        def close(self):
            closed.append(True)

    monkeypatch.setattr(_process_audio_native, "NativeProcessLoopback", Reader)
    monkeypatch.setattr(process_audio, "validate_process_target", lambda target: None)
    monkeypatch.setattr(process_audio.psutil, "Process", lambda pid: SimpleNamespace(is_running=lambda: True))
    monkeypatch.setattr(process_audio.time, "monotonic", lambda: ticks[0])
    process_audio._capture_process_audio(TARGET, packets, errors, stop)
    assert errors.empty()
    assert closed == [True]
    assert packets.get_nowait() == ("connected", b"")
    pcm = []
    while not packets.empty():
        phase, data = packets.get_nowait()
        assert phase == "pcm" and len(data) <= 64000
        pcm.append(data)
    assert len(b"".join(pcm)) >= 3 * 32000
    assert bool(any(b"".join(pcm))) is has_audio


def test_worker_reports_activation_failure_without_global_fallback(monkeypatch):
    from auralwarden import _process_audio_native

    monkeypatch.setattr(process_audio, "validate_process_target", lambda target: None)
    monkeypatch.setattr(_process_audio_native, "NativeProcessLoopback",
                        lambda *args: (_ for _ in ()).throw(WindowsAudioError("Unavailable synthetic API")))
    packets, errors = Channel(maxsize=16), Channel(maxsize=1)
    process_audio._capture_process_audio(TARGET, packets, errors, Event())
    assert packets.empty()
    assert errors.get_nowait() == "Unavailable synthetic API"


def test_process_source_stop_before_start_never_opens_capture(monkeypatch):
    monkeypatch.setattr(process_audio, "validate_process_target", lambda target: None)
    capture = ProcessPcmCapture(TARGET)
    capture.stop()
    assert list(capture.chunks(Event())) == []


def test_window_video_can_use_selected_process_audio_instead_of_system_mix(monkeypatch):
    from auralwarden import window_video

    class Audio:
        def set_status_callback(self, callback):
            self.callback = callback

        def chunks(self, stop):
            self.callback("connected", {})
            yield PcmChunk(bytes(32000), 0, 1)

        def stop(self):
            self.stopped = True

    audio = Audio()
    monkeypatch.setattr(window_video, "validate_target", lambda target: None)
    monkeypatch.setattr(window_video, "WasapiPcmCapture",
                        lambda *args: pytest.fail("Must not open system mix"))
    source = window_video.WindowPcmCapture(SimpleNamespace(), audio_source=audio)
    chunks = list(source.chunks(Event()))
    assert len(chunks) == 1 and audio.stopped


def test_application_mode_requires_explicit_selection_but_not_output_device(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.models import AppSettings
    from auralwarden.settings_store import SettingsStore
    from auralwarden.ui import main_window
    from auralwarden.window_video import WindowTarget

    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_kind="application_audio", source_url="",
                           window_capture_hwnd=999, window_capture_pid=999))
    monkeypatch.setattr(main_window, "list_windows_audio_devices",
                        lambda kind: pytest.fail("Process capture must not enumerate input/output devices"))
    window = main_window.MainWindow(settings_store=store)
    try:
        assert window._selected_window_target is None
        assert window.settings.window_capture_hwnd == 0
        assert window.source_device.isHidden()
        assert window.source_refresh.isHidden()
        assert not window.window_pick_button.isHidden()
        assert not window.silent_button.isHidden()
        assert window.silent_button.text() == "Separar audio"
        assert window.silent_button.isEnabled()
        with pytest.raises(ValueError, match="explícitamente"):
            window.start_monitoring(interactive=False)
        window._selected_window_target = WindowTarget(123, 123, 10, "Synthetic window", "synthetic.exe")
        window.quick_settings.save_full_video.setChecked(True)
        settings = window._collect_settings()
        assert settings.source_kind == "application_audio" and settings.save_full_video
        assert settings.window_capture_pid == 123
        assert settings.system_audio_device == ""
        assert "pestaña" in window.window_pick_button.toolTip()
    finally:
        window._quitting = True
        window.close()
        app.processEvents()


@pytest.mark.parametrize("video", [False, True])
def test_application_source_uses_original_process_audio_for_optional_video(monkeypatch, video):
    pytest.importorskip("PySide6")
    from auralwarden.ui import controller
    from auralwarden.models import AppSettings
    from auralwarden.window_video import WindowTarget

    target = WindowTarget(123, 123, 10, "Synthetic", "synthetic.exe")
    validated_windows = []
    monkeypatch.setattr(controller, "window_target", lambda hwnd: target)
    monkeypatch.setattr(controller, "validate_process_target", lambda target: None)
    monkeypatch.setattr(controller, "validate_target", validated_windows.append)
    monkeypatch.setattr(controller, "WasapiPcmCapture", lambda *args: pytest.fail("No global capture"))
    settings = AppSettings(source_kind="application_audio", window_capture_hwnd=123,
                           window_capture_pid=123, window_capture_created_at=10,
                           save_full_video=video)
    source = controller.build_windows_source(settings)
    capture = source.audio if video else source
    assert isinstance(capture, ProcessPcmCapture)
    assert capture.target == TARGET
    assert len(validated_windows) == int(video)


def test_application_source_rejects_recycled_window_before_capture(monkeypatch):
    pytest.importorskip("PySide6")
    from auralwarden.ui import controller
    from auralwarden.models import AppSettings
    from auralwarden.window_video import WindowTarget

    monkeypatch.setattr(controller, "window_target", lambda hwnd:
                        WindowTarget(123, 888, 20, "Replacement", "other.exe"))
    monkeypatch.setattr(controller, "ProcessPcmCapture", lambda *args: pytest.fail("Must reject reused PID"))
    with pytest.raises(ValueError, match="original"):
        controller.build_windows_source(AppSettings(source_kind="application_audio",
            window_capture_hwnd=123, window_capture_pid=123, window_capture_created_at=10))


def test_application_engine_keeps_transcription_and_cross_fragment_hotword_clips(tmp_path):
    np = pytest.importorskip("numpy")
    from auralwarden.engine import MonitoringEngine
    from auralwarden.models import AppSettings, EventKind, Hotword, ResourceSnapshot
    from auralwarden.transcribers.base import ScriptedTranscriber

    source = ProcessPcmCapture(TARGET)
    tone = (np.sin(np.arange(16000) * 2 * np.pi * 600 / 16000) * 5000).astype(np.int16).tobytes()
    source.chunks = lambda stop: iter(PcmChunk(tone, index, index + 1) for index in range(4))
    settings = AppSettings(source_kind="application_audio", window_capture_pid=123,
        source_url="", hotwords=[Hotword("palabra clave")], save_full_audio=True,
        save_event_audio_clips=True, transcription_window_seconds=1,
        transcription_overlap_seconds=0, clip_pre_seconds=1, clip_post_seconds=1)
    engine = MonitoringEngine(source, ScriptedTranscriber([
        ("Speaker 1", "La palabra"), ("Speaker 1", "clave aparece aquí"),
        ("Speaker 1", "Seguimos hablando"), ("Speaker 1", "Fin del ejemplo"),
    ]), settings, session_root=tmp_path / "sessions")
    engine._resource_sampler = SimpleNamespace(sample=lambda: ResourceSnapshot())
    events = []
    engine.events.subscribe(events.append)
    engine.run_foreground()
    assert engine.error is None
    assert any(event.kind == EventKind.TRANSCRIPT for event in events)
    assert any(event.kind == EventKind.HOTWORD for event in events)
    assert any(event.kind == EventKind.CLIP and event.payload["path"].endswith(".wav") for event in events)
