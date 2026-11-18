import os
import time
from pathlib import Path

import pytest

from auralwarden.stop_timer import StopTimer
from auralwarden.storage import StorageFile, scan_storage, validate_storage_file


def test_duration_starts_when_armed_and_ignores_wall_clock_changes():
    timer = StopTimer()
    timer.configure(duration_seconds=60)
    assert timer.remaining(monotonic_now=100) is None
    timer.arm(monotonic_now=100)
    assert timer.remaining(monotonic_now=110, epoch_now=10**12) == 50
    assert timer.remaining(monotonic_now=160) == 0
    timer.clear()
    assert timer.remaining(monotonic_now=200) is None


def test_absolute_deadline_is_due_after_resume():
    timer = StopTimer()
    target = time.time() + 600
    timer.configure(stop_at_epoch=target)
    assert timer.remaining(epoch_now=target - 2) == 2
    assert timer.remaining(epoch_now=target + 1000) == 0


@pytest.mark.parametrize("value", [True, "60", -1, 0, float("inf"), float("nan"), 10**400, 8 * 86400])
def test_invalid_timer_preserves_previous_configuration(value):
    timer = StopTimer()
    timer.configure(duration_seconds=60)
    with pytest.raises(ValueError):
        timer.configure(duration_seconds=value)
    assert timer.duration_seconds == 60


def test_storage_inventory_classifies_and_protects_configuration(tmp_path):
    for relative in ("settings.json", "models/model.bin", "sessions/one/.video-buffer/a.ts",
                     "sessions/one/clips/audio/a.wav", "sessions/one/transcripts/a.txt"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"example")
    records, complete = scan_storage(tmp_path)
    assert complete and sum(item.size for item in records) == 35
    (tmp_path / "sessions/one/session.json").write_text('{"status":"stopped"}')
    assert {item.category for item in records} == {"other", "models", "recovery", "clips", "transcripts"}
    for record in records:
        if record.category in {"clips", "transcripts"}:
            assert validate_storage_file(tmp_path, record).is_file()
        else:
            with pytest.raises(ValueError):
                validate_storage_file(tmp_path, record)


def test_storage_rejects_changed_and_outside_files(tmp_path):
    folder = tmp_path / "clips"
    folder.mkdir()
    path = folder / "a.wav"
    path.write_bytes(b"abc")
    records, _ = scan_storage(tmp_path)
    path.write_bytes(b"abcd")
    with pytest.raises(ValueError):
        validate_storage_file(tmp_path, records[0])
    with pytest.raises(ValueError):
        validate_storage_file(tmp_path, StorageFile("../clips/a.wav", "clips", 4, 0, 0))


def test_storage_inventory_is_bounded(tmp_path):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("a")
    records, complete = scan_storage(tmp_path, max_files=2)
    assert len(records) == 2 and not complete
    assert scan_storage(tmp_path, cancelled=lambda: True) == ([], False)


def test_storage_preserves_active_sessions(tmp_path):
    folder = tmp_path / "sessions/one/clips"
    folder.mkdir(parents=True)
    (folder / "a.wav").write_bytes(b"example")
    (folder.parent / "session.json").write_text('{"status":"running"}')
    records, _ = scan_storage(tmp_path)
    clip = next(item for item in records if item.category == "clips")
    with pytest.raises(ValueError, match="finalizada"):
        validate_storage_file(tmp_path, clip)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_storage_never_follows_windows_junctions(tmp_path):
    import _winapi
    data = tmp_path / "data"
    outside = tmp_path / "outside"
    data.mkdir()
    outside.mkdir()
    (outside / "private.txt").write_text("keep")
    _winapi.CreateJunction(str(outside), str(data / "clips"))
    records, complete = scan_storage(data)
    assert not records and not complete
    with pytest.raises(ValueError):
        validate_storage_file(data, StorageFile("clips/private.txt", "clips", 4, 0, 0))
    assert (outside / "private.txt").read_text() == "keep"


def test_installed_data_reference_reuses_without_copying_and_fails_closed(tmp_path, monkeypatch):
    from auralwarden import paths
    binary = tmp_path / "application"
    old_data = tmp_path / "old-portable/data"
    binary.mkdir()
    old_data.mkdir(parents=True)
    (old_data / "settings.json").write_text("{}")
    monkeypatch.setattr(paths, "application_root", lambda: binary)
    monkeypatch.delenv("AURALWARDEN_DATA_DIR", raising=False)
    monkeypatch.delenv("AURALWARDEN_PORTABLE", raising=False)
    paths.select_installed_data_dir(old_data)
    assert paths.data_dir() == old_data.resolve()
    assert list(old_data.iterdir()) == [old_data / "settings.json"]
    (old_data / "settings.json").unlink()
    old_data.rmdir()
    with pytest.raises(ValueError, match="disponible"):
        paths.data_dir()


def test_paths_installed_and_portable_keep_different_roots(tmp_path, monkeypatch):
    from auralwarden import paths
    binary = tmp_path / "Programs" / "AuralWarden"
    binary.mkdir(parents=True)
    monkeypatch.setattr(paths, "application_root", lambda: binary)
    monkeypatch.delenv("AURALWARDEN_DATA_DIR", raising=False)
    monkeypatch.delenv("AURALWARDEN_PORTABLE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    assert paths.data_dir() == tmp_path / "user-data" / "AuralWarden"
    (binary / "portable.flag").touch()
    assert paths.data_dir() == binary / "data"


def test_installer_preserves_user_data_and_never_forces_app_closure():
    script = (Path(__file__).resolve().parents[1] / "installer" / "AuralWarden.iss").read_text()
    assert "PrivilegesRequired=lowest" in script
    assert "CloseApplications=no" in script
    assert "RestartApplications=no" in script
    assert "AppMutex=Local\\Yojemr.AuralWarden.Installed" in script
    assert "portable.flag,data\\*" in script
    assert "[UninstallDelete]" not in script


def test_timer_uses_normal_stop_and_only_fires_once(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from auralwarden.ui.main_window import MainWindow
    from auralwarden.settings_store import SettingsStore
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    calls = []
    monkeypatch.setattr(window, "controller", SimpleNamespace(running=True, stop=lambda: calls.append("stop"),
        session_path=None, engine=None))
    monkeypatch.setattr(window, "_set_state", lambda state: None)
    monkeypatch.setattr(window, "_restore_silent_audio", lambda message: calls.append("restore"))
    try:
        window.stop_timer.configure(duration_seconds=1)
        window.stop_timer.arm(monotonic_now=time.monotonic() - 2)
        window._update_elapsed()
        window._update_elapsed()
        assert calls == ["restore", "stop"]
    finally:
        window._clock.stop()
        window._audio_guard.stop()
        window._state_guard.stop()
        window.tray.hide()
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_storage_trash_requires_confirmation_and_never_falls_back_to_delete(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from auralwarden.ui import maintenance_dialogs as ui
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "clips"
    folder.mkdir()
    original = folder / "sample.wav"
    original.write_bytes(b"keep")
    dialog = ui.StorageDialog(tmp_path, lambda: True)
    assert dialog.worker.wait(5000)
    app.processEvents()
    row = next(row for row in range(dialog.table.rowCount()) if dialog.table.item(row, 0).text().endswith("sample.wav"))
    dialog.table.selectRow(row)
    calls = []
    monkeypatch.setattr(ui.QFile, "moveToTrash", lambda path: calls.append(path) or (False, ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    dialog.move_selected()
    assert not calls and original.read_bytes() == b"keep"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.move_selected()
    assert len(calls) == 1 and original.read_bytes() == b"keep"
    if dialog.worker.isRunning():
        assert dialog.worker.wait(5000)
    app.processEvents()
    dialog.close()
    app.processEvents()


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_installed_guard_keeps_its_identity_until_closed(monkeypatch):
    import uuid
    from auralwarden import install_guard
    monkeypatch.setattr(install_guard, "INSTALLED_MUTEX", "Local\\AuralWarden.Test." + uuid.uuid4().hex)
    first, second = install_guard.InstalledAppGuard(), install_guard.InstalledAppGuard()
    try:
        first.claim()
        with pytest.raises(RuntimeError, match="en uso"):
            second.claim()
    finally:
        first.close()
    second.claim()
    second.close()
