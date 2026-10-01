from __future__ import annotations

import json

import numpy as np
import pytest
from types import SimpleNamespace

from auralwarden.windows_audio import (
    EndpointState,
    SilentMonitoringManager,
    _downmix_and_resample,
    WasapiPcmCapture,
    WindowsAudioError,
)


class FakeEndpointBackend:
    def __init__(self) -> None:
        self.current = EndpointState("device-1", "Altavoces", False, 0.5)
        self.applied: list[EndpointState] = []

    def snapshot(self, device_name: str = "") -> EndpointState:
        return self.current

    def apply(self, state: EndpointState) -> None:
        self.current = state
        self.applied.append(state)


def test_downmixes_and_resamples_to_whisper_format() -> None:
    left = np.arange(0, 4800, dtype=np.int16)
    right = np.arange(4800, 0, -1, dtype=np.int16)
    stereo = np.column_stack([left, right]).astype(np.int16).tobytes()

    converted = _downmix_and_resample(stereo, 2, 48_000, 16_000)

    samples = np.frombuffer(converted, dtype=np.int16)
    assert samples.size == 1600
    assert 2398 <= int(samples.mean()) <= 2402


def test_silent_monitoring_restores_original_state(tmp_path) -> None:
    backend = FakeEndpointBackend()
    manager = SilentMonitoringManager(tmp_path / "silent.json", backend)

    original = manager.activate("Altavoces")

    assert original.volume == 0.5
    assert manager.active
    assert backend.current.muted
    assert manager.restore_original()
    assert not backend.current.muted
    assert backend.current.volume == 0.5
    assert not manager.state_path.exists()


def test_hotword_reveals_audio_and_leaves_it_enabled(tmp_path) -> None:
    backend = FakeEndpointBackend()
    backend.current = EndpointState("device-1", "Altavoces", True, 0.0)
    manager = SilentMonitoringManager(tmp_path / "silent.json", backend)
    manager.activate("Altavoces")

    assert manager.reveal_for_alert()

    assert not manager.active
    assert not backend.current.muted
    assert backend.current.volume == 0.25
    assert not manager.state_path.exists()


def test_interrupted_session_is_recovered_on_next_launch(tmp_path) -> None:
    path = tmp_path / "silent.json"
    path.write_text(
        json.dumps(
            {
                "device_id": "device-1",
                "device_name": "Altavoces",
                "muted": False,
                "volume": 0.4,
            }
        ),
        encoding="utf-8",
    )
    backend = FakeEndpointBackend()
    backend.current = EndpointState("device-1", "Altavoces", True, 0.4)
    manager = SilentMonitoringManager(path, backend)

    assert manager.recover_interrupted()
    assert not backend.current.muted
    assert backend.current.volume == 0.4
    assert not path.exists()


def test_missing_explicit_device_does_not_capture_another_device():
    capture = WasapiPcmCapture("system_audio", "Missing synthetic device")
    manager = SimpleNamespace(
        get_host_api_info_by_type=lambda *_: {"index": 1, "defaultOutputDevice": 0},
        get_device_info_generator=lambda: iter([{
            "name": "Other synthetic device", "hostApi": 1, "isLoopbackDevice": True,
        }]),
    )
    with pytest.raises(WindowsAudioError, match="ya no está disponible"):
        capture._resolve_devices(manager, SimpleNamespace(paWASAPI=1))


def test_failed_startup_audio_restore_remains_visible_and_retryable(tmp_path):
    backend = FakeEndpointBackend()
    path = tmp_path / "synthetic-state.json"
    first = SilentMonitoringManager(path, backend)
    first.activate()
    manager = SilentMonitoringManager(path, backend)
    original_apply = backend.apply
    backend.apply = lambda *_: (_ for _ in ()).throw(OSError("synthetic unavailable device"))
    with pytest.raises(OSError):
        manager.recover_interrupted()
    assert manager.active and path.exists()
    backend.apply = original_apply
    assert manager.recover_interrupted()
    assert not manager.active and not path.exists()
