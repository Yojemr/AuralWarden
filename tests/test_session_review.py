import json
import wave
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from auralwarden.bookmarks import BookmarkStore
from auralwarden.models import AppSettings, EventKind, Hotword, ResourceSnapshot, SessionState


def test_bookmarks_keep_original_transcripts_unchanged_and_share_session_scope(tmp_path):
    session = tmp_path / "session"
    folder = session / "transcripts"
    folder.mkdir(parents=True)
    (session / "session.json").write_text("{}", encoding="utf-8")
    original = folder / "transcript.txt"
    original.write_text("Original class transcript", encoding="utf-8")
    saved = original.read_bytes()
    store = BookmarkStore(tmp_path / "private" / "bookmarks.json")
    first = store.add(session, 12, "Important moment")
    second = store.add(original, 5, "Earlier point")
    assert [item["id"] for item in store.records(session)] == [second["id"], first["id"]]
    assert store.records(original) == store.records(session)
    assert original.read_bytes() == saved
    assert sorted(path.name for path in folder.iterdir()) == ["transcript.txt"]


@pytest.mark.parametrize("elapsed,note", [(float("nan"), "note"), (float("inf"), "note"),
    (-1, "note"), (0, ""), (0, "a" * 1001)])
def test_invalid_bookmark_does_not_create_a_file(tmp_path, elapsed, note):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    with pytest.raises(ValueError):
        store.add(tmp_path, elapsed, note)
    assert not store.path.exists()


@pytest.mark.parametrize("elapsed", [10 ** 400, None, True], ids=["overflow", "null", "boolean"])
def test_unrepresentable_bookmark_time_is_a_validation_error(tmp_path, elapsed):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    with pytest.raises(ValueError):
        store.add(tmp_path, elapsed, "note")
    assert not store.path.exists()


def test_huge_time_in_existing_bookmark_file_is_rejected_without_overwriting(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.path.write_text(json.dumps({"schema": 1, "bookmarks": [{"id": "sample", "scope": str(tmp_path),
        "note": "keep", "created_at": "2026-11-06", "elapsed_seconds": 10 ** 400}]}), encoding="utf-8")
    original = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.records(tmp_path)
    assert store.path.read_bytes() == original


def test_capitalized_transcript_directory_preserves_bookmark_session_scope(tmp_path):
    session = tmp_path / "session"
    folder = session / "Transcripts"
    folder.mkdir(parents=True)
    (session / "session.json").write_text("{}", encoding="utf-8")
    path = folder / "example.txt"
    path.write_text("sample", encoding="utf-8")
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.add(session, 3, "sample")
    assert len(store.records(path)) == 1


def test_bookmark_deletion_cannot_change_another_session(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    mark = store.add(first, 10, "Keep me")
    store.delete(second, mark["id"])
    assert len(store.records(first)) == 1
    store.delete(first, mark["id"])
    assert store.records(first) == []


def test_corrupted_bookmarks_are_not_overwritten(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        store.add(tmp_path, 3, "note")
    assert store.path.read_text(encoding="utf-8") == "broken"


def test_bookmark_capacity_is_explicit_and_does_not_drop_old_notes(tmp_path, monkeypatch):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    monkeypatch.setattr(store, "MAX_ITEMS", 1)
    store.add(tmp_path, 1, "first")
    with pytest.raises(ValueError, match="límite"):
        store.add(tmp_path, 2, "second")
    assert store.records(tmp_path)[0]["note"] == "first"


def test_transcript_search_navigates_unicode_literal_matches_without_rewriting(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.ui.management_dialogs import TranscriptLibraryDialog
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "example.txt"
    path.write_text("😀 Clave y CLAVE. Literal [a] [a]", encoding="utf-8")
    original = path.read_bytes()
    dialog = TranscriptLibraryDialog(tmp_path, bookmark_store=BookmarkStore(tmp_path / "bookmarks.json"))
    try:
        assert dialog.open_path(path)
        dialog.content_search.setText("clave")
        dialog._update_content_matches()
        assert len(dialog._content_matches) == 2
        assert dialog.viewer.textCursor().selectedText() == "Clave"
        dialog._move_content_match(1)
        assert dialog.viewer.textCursor().selectedText() == "CLAVE"
        dialog._move_content_match(1)
        assert dialog.viewer.textCursor().selectedText() == "Clave"
        dialog.content_search.setText("[a]")
        dialog._update_content_matches()
        assert len(dialog._content_matches) == 2
        dialog.content_search.setText("missing")
        dialog._update_content_matches()
        assert not dialog.next_match.isEnabled()
        assert not dialog.viewer.textCursor().hasSelection()
        assert path.read_bytes() == original
        assert dialog.moments_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_manual_clip_uses_captured_clock_and_does_not_trigger_a_hotword(tmp_path):
    np = pytest.importorskip("numpy")
    from auralwarden.audio import PcmChunk
    from auralwarden.engine import MonitoringEngine
    from auralwarden.transcribers.base import ScriptedTranscriber
    released = Event()
    reached = Event()
    tone = (np.sin(np.arange(16000) * 2 * np.pi * 500 / 16000) * 4000).astype(np.int16).tobytes()

    class Source:
        def chunks(self, stop):
            for index in range(6):
                yield PcmChunk(tone, index, index + 1)
                if index == 1:
                    reached.set()
                    assert released.wait(3)

        def stop(self):
            released.set()

    settings = AppSettings(hotwords=[Hotword("clave")], transcription_window_seconds=1,
        transcription_overlap_seconds=0, clip_pre_seconds=1, clip_post_seconds=2,
        save_event_audio_clips=True, save_event_video_clips=False)
    engine = MonitoringEngine(Source(), ScriptedTranscriber([
        ("Speaker 1", text) for text in ("inicio", "seguimos", "clave", "seguimos", "casi fin", "fin")
    ]), settings, session_root=tmp_path)
    engine._resource_sampler = SimpleNamespace(sample=lambda: ResourceSnapshot())
    events = []
    requested = []

    def on_event(event):
        events.append(event)
        if event.kind == EventKind.TRANSCRIPT and not requested:
            assert reached.wait(3)
            requested.append(engine.request_manual_clip())
            assert engine._manual_clips[0][0].elapsed_seconds == 2
            released.set()

    engine.events.subscribe(on_event)
    engine.run_foreground()
    assert engine.error is None
    matches = [event for event in events if event.kind == EventKind.HOTWORD]
    assert len(matches) == 1 and matches[0].payload["phrase"] == "clave"
    clip = next(event for event in events if event.kind == EventKind.CLIP and event.payload["event_id"] == requested[0])
    with wave.open(clip.payload["path"]) as audio:
        assert audio.getnframes() == 3 * 16000
    assert not clip.payload["truncated"]
    assert engine._manual_outstanding == {}


def test_enter_after_changing_search_uses_the_new_query_immediately(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.ui.management_dialogs import TranscriptLibraryDialog
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "example.txt"
    path.write_text("clave y clave, después manual", encoding="utf-8")
    dialog = TranscriptLibraryDialog(tmp_path)
    try:
        dialog.open_path(path)
        dialog.content_search.setText("clave")
        dialog._update_content_matches()
        dialog.content_search.setText("manual")
        dialog.content_search.returnPressed.emit()
        assert dialog.viewer.textCursor().selectedText() == "manual"
        assert dialog.match_count.text() == "1/1"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_manual_request_queue_is_bounded_and_snapshots_clip_preferences(tmp_path):
    from auralwarden.engine import MonitoringEngine
    from auralwarden.transcribers.base import ScriptedTranscriber
    engine = MonitoringEngine(SimpleNamespace(), ScriptedTranscriber([]), AppSettings(), session_root=tmp_path)
    with pytest.raises(ValueError):
        engine.request_manual_clip()
    engine.state = SessionState.RUNNING
    engine._reader = SimpleNamespace(captured_until_seconds=10)
    for _ in range(8):
        engine.request_manual_clip()
    with pytest.raises(ValueError, match="ocho"):
        engine.request_manual_clip()
    engine._requested_clips = (False, False)
    assert all(audio and not video for _, audio, video in engine._manual_clips)
    with pytest.raises(ValueError, match="tipo de clip"):
        engine.request_manual_clip()


def test_manual_video_uses_same_timestamp_and_completes_both_media(tmp_path):
    from auralwarden.engine import MonitoringEngine
    from auralwarden.clips import CompletedAudioClip
    from auralwarden.video_clips import CompletedVideoClip
    from auralwarden.transcribers.base import ScriptedTranscriber
    engine = MonitoringEngine(SimpleNamespace(), ScriptedTranscriber([]),
        AppSettings(save_event_audio_clips=True, save_event_video_clips=True), session_root=tmp_path)
    engine.state = SessionState.RUNNING
    engine._reader = SimpleNamespace(captured_until_seconds=12)
    event_id = engine.request_manual_clip()
    scheduled = []

    def audio(event, captured):
        scheduled.append(("audio", event.elapsed_seconds))
        return [CompletedAudioClip(event.event_id, tmp_path / "manual.wav", False)]

    def video(event, captured):
        scheduled.append(("video", event.elapsed_seconds))
        return [CompletedVideoClip(event.event_id, tmp_path / "manual.mp4", False)]

    engine._drain_manual_clips(12, SimpleNamespace(schedule=audio), SimpleNamespace(schedule=video))
    assert scheduled == [("audio", 12), ("video", 12)]
    assert event_id not in engine._manual_outstanding


def test_manual_activity_is_not_labelled_as_a_detected_hotword():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.ui.widgets import ActivityFeed
    app = QApplication.instance() or QApplication([])
    feed = ActivityFeed()
    try:
        feed.add_detection({"manual": True, "event_id": "manual", "phrase": "Clip manual", "audio_clip_requested": True})
        card = feed._by_event["manual"]
        assert card.score_text.text() == "Acción manual · sin hotword"
        assert feed.total.text() == "1 elemento"
        feed.mark_clip({"event_id": "manual", "path": "synthetic.wav", "truncated": True})
        assert "parcial" in card.clip_label.text().casefold()
    finally:
        feed.deleteLater()
        app.processEvents()


def test_manual_request_is_cancelled_explicitly_if_capture_fails_before_processing(tmp_path):
    np = pytest.importorskip("numpy")
    from auralwarden.audio import PcmChunk
    from auralwarden.engine import MonitoringEngine
    from auralwarden.transcribers.base import ScriptedTranscriber
    tone = (np.sin(np.arange(16000) * 2 * np.pi * 500 / 16000) * 4000).astype(np.int16).tobytes()

    class Source:
        def chunks(self, stop):
            yield PcmChunk(tone, 0, 1)
            raise RuntimeError("Synthetic source failure")

        def stop(self):
            pass

    engine = MonitoringEngine(Source(), ScriptedTranscriber([("Speaker 1", "hello")]),
        AppSettings(hotwords=[], transcription_window_seconds=1, transcription_overlap_seconds=0),
        session_root=tmp_path)
    engine._resource_sampler = SimpleNamespace(sample=lambda: ResourceSnapshot())
    events = []

    def on_event(event):
        events.append(event)
        if event.kind == EventKind.TRANSCRIPT:
            engine.request_manual_clip()

    engine.events.subscribe(on_event)
    engine.run_foreground()
    assert engine.error
    assert any(event.payload.get("code") == "manual_clip_cancelled" for event in events)
    assert not engine._manual_outstanding


def test_manual_gui_event_does_not_notify_restore_sound_or_register_hotword(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from auralwarden.models import EngineEvent
    from auralwarden.settings_store import SettingsStore
    from auralwarden.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    monkeypatch.setattr(window, "_notify", lambda *args: pytest.fail("A manual clip must not sound as a hotword"))
    monkeypatch.setattr(window, "_reveal_audio_for_alert", lambda *args: pytest.fail("A manual clip must not change audio routing"))
    try:
        window._handle_event(EngineEvent(EventKind.INFO, {"code": "manual_clip_requested", "event_id": "manual",
            "manual": True, "phrase": "Clip manual", "elapsed_seconds": 12, "audio_clip_requested": True}))
        assert window.activity._by_event["manual"].is_manual
        assert window._last_match == "Sin coincidencias"
        assert not window.alert_history.records()
    finally:
        window._quitting = True
        window.close()
        window.deleteLater()
        app.processEvents()
