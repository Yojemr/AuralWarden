from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from auralwarden import audio_routing
from auralwarden.audio_routing import ApplicationAudioRouter, RouteTransaction, read_route_json, write_route_json
from auralwarden.process_audio import ProcessTarget
from auralwarden.windows_audio import WindowsAudioError


TARGET = ProcessTarget(123, 10.0, "synthetic.exe")
CABLE = "{0.0.0.00000000}.{synthetic-cable}"


class Backend:
    def __init__(self):
        self.values = {0: "", 1: "physical-output", 2: ""}
        self.target = TARGET
        self.present = True
        self.fail_role = None
        self.default = "physical-output"
        self.calls = []

    def available(self, endpoint):
        return self.present

    def default_output(self, role):
        return self.default

    def routed_outputs(self, target):
        return {self.values[1]}

    def candidate(self, target, **kwargs):
        return self.target

    def get(self, target, role):
        return self.values[role]

    def set(self, target, role, endpoint):
        self.calls.append((target.pid, role, endpoint))
        self.values[role] = endpoint
        if role == self.fail_role:
            self.fail_role = None
            raise WindowsAudioError("Synthetic partial change")


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_routing, "validate_process_target", lambda target: None)
    path = tmp_path / "route.json"
    write_route_json(path, {"lease": "a" * 32, "phase": "requested", "target": asdict(TARGET),
                           "endpoint_id": CABLE, "originals": {}})
    backend = Backend()
    return RouteTransaction(path, backend), backend, path


def test_route_preserves_all_original_roles_and_restores_after_alert(route):
    transaction, backend, path = route
    originals = dict(backend.values)
    transaction.activate()
    saved = read_route_json(path)
    assert saved["phase"] == "active"
    assert saved["originals"] == {str(k): v for k, v in originals.items()}
    assert set(backend.values.values()) == {CABLE}
    assert transaction.restore()
    assert backend.values == originals
    assert read_route_json(path) == {"lease": "a" * 32, "phase": "restored", "error": ""}


def test_partial_activation_rolls_back_changed_roles(route):
    transaction, backend, path = route
    originals = dict(backend.values)
    backend.fail_role = 1
    with pytest.raises(WindowsAudioError, match="partial"):
        transaction.activate()
    assert backend.values == originals
    assert read_route_json(path)["phase"] == "restored"


def test_preference_change_is_not_enough_if_stream_stays_on_speakers(route, monkeypatch):
    transaction, backend, path = route
    originals = dict(backend.values)
    backend.routed_outputs = lambda target: {"physical-output"}
    times = iter([0, 3, 10])
    monkeypatch.setattr(audio_routing.time, "monotonic", lambda: next(times))
    with pytest.raises(WindowsAudioError, match="no cambió"):
        transaction.activate()
    assert backend.values == originals
    assert read_route_json(path)["phase"] == "restored"


def test_restore_keeps_journal_if_stream_ignores_restored_preferences(route, monkeypatch):
    transaction, backend, path = route
    originals = dict(backend.values)
    transaction.activate()
    backend.routed_outputs = lambda target: {CABLE}
    times = iter([0, 3])
    monkeypatch.setattr(audio_routing.time, "monotonic", lambda: next(times))
    assert not transaction.restore()
    assert backend.values == originals
    saved = read_route_json(path)
    assert saved["phase"] == "waiting" and len(saved["originals"]) == 3


def test_recovery_respects_manual_output_change(route):
    transaction, backend, path = route
    transaction.activate()
    backend.values[1] = "user-selected-headphones"
    assert transaction.check_external_change()
    transaction.restore()
    assert backend.values == {0: "", 1: "user-selected-headphones", 2: ""}


def test_closed_application_keeps_recovery_until_a_verified_instance_exists(route):
    transaction, backend, path = route
    transaction.activate()
    backend.target = None
    assert not transaction.restore()
    assert read_route_json(path)["phase"] == "waiting"
    assert len(read_route_json(path)["originals"]) == 3
    backend.target = ProcessTarget(456, 20, "synthetic.exe")
    assert transaction.restore()
    assert read_route_json(path)["phase"] == "restored"
    assert backend.calls[-1][0] == 456


@pytest.mark.parametrize("case", ["missing", "already-routed", "global-default", "no-session"])
def test_invalid_route_does_not_change_any_preferences(route, case):
    transaction, backend, path = route
    if case == "missing":
        backend.present = False
    elif case == "already-routed":
        backend.values[1] = CABLE
    elif case == "global-default":
        backend.default = CABLE
    else:
        backend.target = None
    with pytest.raises(WindowsAudioError):
        transaction.activate()
    assert backend.calls == []


def test_journal_exists_before_first_windows_preference_change(route):
    transaction, backend, path = route
    original_set = backend.set

    def checked_set(target, role, endpoint):
        state = read_route_json(path)
        assert state["phase"] == "preparing" and len(state["originals"]) == 3
        original_set(target, role, endpoint)

    backend.set = checked_set
    transaction.activate()


@pytest.mark.parametrize("originals", [{"9": "output"}, {"0": 123}, []])
def test_invalid_recovery_record_is_rejected_before_windows_calls(tmp_path, originals):
    path = tmp_path / "route.json"
    write_route_json(path, {"lease": "a" * 32, "phase": "pending", "target": asdict(TARGET),
                           "endpoint_id": CABLE, "originals": originals})
    with pytest.raises(WindowsAudioError):
        RouteTransaction(path, Backend())


def test_damaged_record_remains_visible_as_pending(tmp_path):
    path = tmp_path / "route.json"
    path.write_text("not json", encoding="utf-8")
    router = ApplicationAudioRouter(path)
    assert router.active and router.status_message


def test_oversized_record_is_rejected(tmp_path):
    path = tmp_path / "route.json"
    path.write_text(" " * 20000, encoding="utf-8")
    with pytest.raises(WindowsAudioError):
        read_route_json(path)


def test_renderer_handshake_is_bounded_and_does_not_accept_invalid_pid():
    from io import StringIO
    from auralwarden.audio_routing_check import _renderer_pid
    assert _renderer_pid(StringIO('{"pid": 123}\n')) == 123
    with pytest.raises(RuntimeError, match="iniciarse"):
        _renderer_pid(StringIO("invalid"))


def test_renderer_handshake_times_out_without_blocking_main_thread():
    from threading import Event
    from auralwarden.audio_routing_check import _renderer_pid
    unblock = Event()
    reader = SimpleNamespace(readline=lambda size: unblock.wait(1) or "")
    try:
        with pytest.raises(RuntimeError, match="tiempo"):
            _renderer_pid(reader, timeout=0.01)
    finally:
        unblock.set()


def test_install_default_snapshot_is_recovered_without_touching_unrelated_outputs(tmp_path, monkeypatch):
    from auralwarden import virtual_audio_install as install
    defaults = [(0, 0, "physical-output"), (1, 0, "microphone")]
    install.save_install_defaults(tmp_path, defaults)
    restored = []
    monkeypatch.setattr(audio_routing, "list_virtual_outputs", lambda: ["installed-standard-cable"])
    monkeypatch.setattr(install, "preserve_audio_defaults", restored.append)
    assert install.recover_install_defaults(tmp_path)
    assert restored == [[list(row) for row in defaults]]
    assert not (tmp_path / "virtual-audio-install-state.json").exists()


def test_guard_duplicate_never_restores_or_rewrites_other_owners_journal(tmp_path, monkeypatch):
    from auralwarden import audio_route_guard as guard
    path = tmp_path / "route.json"
    write_route_json(path, {"phase": "active", "originals": {"0": "physical"}})
    original = path.read_bytes()
    transaction = SimpleNamespace(state={}, root=TARGET, originals={"0": "physical"},
        restore=lambda: pytest.fail("Duplicate guard must not restore another owner's audio"))
    native = SimpleNamespace(CreateMutexW=lambda *args: 123, CloseHandle=lambda handle: True)
    monkeypatch.setattr(guard, "NativeRouteBackend", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guard, "RouteTransaction", lambda *args: transaction)
    monkeypatch.setattr(guard.C, "WinDLL", lambda *args, **kwargs: native, raising=False)
    monkeypatch.setattr(guard.C, "get_last_error", lambda: 183, raising=False)
    assert guard.run_guard(path) == 1
    assert path.read_bytes() == original


def test_guard_restores_if_owner_was_replaced_before_activation(tmp_path, monkeypatch):
    from auralwarden import audio_route_guard as guard
    path = tmp_path / "route.json"
    state = {"phase": "requested", "owner_pid": 100, "owner_created_at": 10}
    calls = []
    transaction = SimpleNamespace(state=state, root=TARGET, originals={}, lease="a" * 32,
        activate=lambda: pytest.fail("Recycled owner must not activate"),
        restore=lambda: calls.append("restore") or True)
    native = SimpleNamespace(CreateMutexW=lambda *args: 123, CloseHandle=lambda handle: True)
    monkeypatch.setattr(guard, "NativeRouteBackend", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guard, "RouteTransaction", lambda *args: transaction)
    monkeypatch.setattr(guard.C, "WinDLL", lambda *args, **kwargs: native, raising=False)
    monkeypatch.setattr(guard.C, "get_last_error", lambda: 0, raising=False)
    monkeypatch.setattr(guard.psutil, "Process", lambda *args: SimpleNamespace(pid=200,
        create_time=lambda: 20, is_running=lambda: True))
    assert guard.run_guard(path) == 0 and calls == ["restore"]


def test_restore_waits_for_existing_guard_to_retry_a_pending_record(tmp_path, monkeypatch):
    router = ApplicationAudioRouter(tmp_path / "route.json")
    states = iter([{"phase": "pending", "lease": "a" * 32},
                   {"phase": "pending"}, {"phase": "pending"}, {"phase": "restored"}])
    monkeypatch.setattr(ApplicationAudioRouter, "state", property(lambda self: next(states)))
    monkeypatch.setattr(router, "_ensure_guard", lambda: None)
    monkeypatch.setattr(audio_routing.time, "sleep", lambda delay: None)
    assert router.restore_original()


def test_installer_rejects_tampered_cached_executable(tmp_path, monkeypatch):
    from auralwarden import virtual_audio_install as install
    executable = tmp_path / "VBCABLE_Setup_x64.exe"
    executable.write_bytes(b"synthetic untrusted installer")
    monkeypatch.setattr(install, "ComponentManager", lambda root: SimpleNamespace(find_executable=lambda spec: executable))
    with pytest.raises(Exception, match="verificada"):
        install.prepare_vb_cable(tmp_path)


def test_hotword_restores_application_routing_without_muting_system(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.ui.main_window import MainWindow
    from auralwarden.models import AppSettings
    from auralwarden.settings_store import SettingsStore

    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / "settings.json")
    store.save(AppSettings(source_kind="application_audio", source_url=""))
    window = MainWindow(settings_store=store)

    class Router:
        active = True

        def restore_original(self):
            self.active = False
            return True

    window.application_router = Router()
    monkeypatch.setattr(window.silent_audio.backend, "apply", lambda state: pytest.fail("No global volume changes"))
    try:
        window._reveal_audio_for_alert("synthetic alert")
        assert not window.application_router.active
        assert "synthetic alert" in window.status_label.toolTip()
        assert window.silent_button.text() == "Separar audio"
    finally:
        window._quitting = True
        window.close()
        window.deleteLater()
        app.processEvents()
