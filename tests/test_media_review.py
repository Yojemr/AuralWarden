import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from threading import Event

import pytest

from auralwarden import media_review as media
from auralwarden.models import TranscriptEntry
from auralwarden.transcript_archive import render_archived_transcript
from auralwarden.transcript_review import review_text, text_spans, utf16_length


@pytest.mark.parametrize("value", ["00:00:00", "01:23:45.678", "123:00:01,5"])
def test_review_time_roundtrip(value):
    seconds = media.parse_time(value)
    assert media.parse_time(media.format_time(seconds)) == seconds


@pytest.mark.parametrize("value", ["-1:00:00", "00:61:00", "nan", "10", "1:2:3", "00:00:00.1234"])
def test_review_time_rejects_invalid_input(value):
    with pytest.raises(ValueError):
        media.parse_time(value)


def test_timeline_maps_gaps_and_rejects_incomplete_exports(tmp_path):
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"synthetic")
    media.save_timeline(video, [(2, 5), (10, 13)])
    timeline = media.load_timeline(video)
    assert timeline.known
    assert timeline.to_media(3) == 1
    assert timeline.to_media(11) == 4
    assert timeline.to_session(4) == 11
    assert timeline.to_media(21, shift=10) == 4
    assert timeline.interval(2, 5) == (0, 3)
    assert timeline.interval(10, 13) == (3, 6)
    for start, end in [(3, 11), (5, 11), (0, 2), (3, 7), (11, 10)]:
        with pytest.raises(ValueError):
            timeline.interval(start, end)
    with pytest.raises(ValueError):
        timeline.to_media(7)
    original = media.timeline_path(video).read_bytes()
    with pytest.raises(FileExistsError):
        media.save_timeline(video, [(0, 3)])
    assert media.timeline_path(video).read_bytes() == original
    video.write_bytes(b"changed video")
    with pytest.raises(ValueError, match="cambió"):
        media.load_timeline(video)


@pytest.mark.parametrize("ranges", [[(1, 3), (2, 5)], [(0, float("inf"))], [(-1, 2)], [(2, 1)]])
def test_malformed_timeline_is_not_silently_trusted(tmp_path, ranges):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"test")
    media.save_timeline(path, ranges)
    with pytest.raises(ValueError):
        media.load_timeline(path)


def test_review_text_preserves_layout_and_utf16_fragment_positions():
    entries = [TranscriptEntry(1, "Speaker 1", "Primera frase 😀 palabra clave", end_seconds=3),
               TranscriptEntry(3, "Speaker 1", "Segunda frase", end_seconds=4),
               TranscriptEntry(20, "Speaker 2", "Otro párrafo", end_seconds=21)]
    text, spans = review_text(entries)
    assert text == render_archived_transcript(entries)
    for entry, span in zip(entries, spans):
        extracted = text.encode("utf-16-le")[span.start * 2:span.end * 2].decode("utf-16-le")
        assert extracted == entry.text
        assert span.seconds == entry.elapsed_seconds
    assert utf16_length("😀") == 2
    txt = "Title\n[00:00:01] Speaker: Hola 😀\n\n[00:02:03] Speaker: Después"
    txt_ranges = text_spans(txt)
    assert [span.seconds for span in txt_ranges] == [1, 123]
    assert txt_ranges[-1].end == utf16_length(txt)


def test_media_discovery_uses_only_completed_session_recordings(tmp_path):
    folder = tmp_path / "session"
    recordings, transcripts = folder / "recordings", folder / "transcripts"
    recordings.mkdir(parents=True)
    transcripts.mkdir()
    transcript = transcripts / "class.json"
    video = recordings / "2026 - Video completo.mp4"
    video.write_bytes(b"test")
    metadata = folder / "session.json"
    metadata.write_text('{"status":"running"}')
    assert media.discover_session_media(transcript) is None
    metadata.write_text('{"status":"stopped","full_video":"https://untrusted.invalid/remote.mp4"}')
    assert media.discover_session_media(transcript) == video
    (recordings / "another - Video completo.mp4").write_bytes(b"other")
    assert media.discover_session_media(transcript) is None


@pytest.fixture
def synthetic_video(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe required for real media validation")
    path = tmp_path / "synthetic.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "3", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-shortest", str(path)],
        capture_output=True, check=True, timeout=30, creationflags=media.NO_WINDOW)
    return path


def test_real_export_is_precise_and_preserves_original(synthetic_video):
    before = hashlib.sha256(synthetic_video.read_bytes()).hexdigest()
    destination = synthetic_video.with_name("selected.mp4")
    result = media.export_interval(synthetic_video, destination, 0.7, 2.0, session_start=10)
    duration, video = media.probe_media(result)
    assert video and abs(duration - 1.3) < 0.2
    assert hashlib.sha256(synthetic_video.read_bytes()).hexdigest() == before
    assert media.load_timeline(result).to_media(10.5) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        media.export_interval(synthetic_video, destination, 0, 1)
    with pytest.raises(ValueError):
        media.export_interval(synthetic_video, synthetic_video, 0, 1)


def test_real_audio_export_and_cancellation(tmp_path):
    import wave
    path = tmp_path / "source.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 32000)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe required")
    result = media.export_interval(path, tmp_path / "clip.wav", 0.2, 0.9)
    duration, video = media.probe_media(result)
    assert not video and duration == pytest.approx(0.7, abs=0.02)
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        media.export_interval(path, tmp_path / "cancelled.wav", 0, 1, cancel=cancel)
    assert not (tmp_path / "cancelled.wav").exists()


def test_destination_race_never_overwrites_another_file(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.mp4", tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(media, "probe_media", lambda _: (3, True))
    monkeypatch.setattr(media, "runtime_executable", lambda _: "ffmpeg")
    class Process:
        returncode = 0
        def poll(self): return 0
    def launch(command, **kwargs):
        Path(command[-1]).write_bytes(b"new clip")
        destination.write_bytes(b"other file")
        return Process()
    monkeypatch.setattr(media.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="destino apareció"):
        media.export_interval(source, destination, 0, 1)
    assert destination.read_bytes() == b"other file"
    assert not list(tmp_path.glob(".auralwarden-export-*"))


def test_mid_export_cancel_terminates_only_its_child(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    cancel, calls = Event(), []
    monkeypatch.setattr(media, "probe_media", lambda _: (3, True))
    monkeypatch.setattr(media, "runtime_executable", lambda _: "ffmpeg")
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def terminate(self): calls.append("terminate"); self.returncode = -15
        def wait(self, timeout): return self.returncode
    def launch(*args, **kwargs):
        cancel.set()
        return Process()
    monkeypatch.setattr(media.subprocess, "Popen", launch)
    with pytest.raises(InterruptedError):
        media.export_interval(source, tmp_path / "clip.mp4", 0, 1, cancel=cancel)
    assert calls == ["terminate"]
    assert source.read_bytes() == b"source"
    assert not list(tmp_path.glob(".auralwarden-export-*"))


def test_library_keeps_player_lazy_and_search_literal(qt_application_lifetime, tmp_path):
    from auralwarden.ui.management_dialogs import TranscriptLibraryDialog
    transcript = tmp_path / "class.json"
    transcript.write_text(json.dumps([{"elapsed_seconds": 1, "text": "Una frase 😀 con palabra clave"},
                                    {"elapsed_seconds": 3, "text": "Otra frase"}]))
    dialog = TranscriptLibraryDialog(tmp_path)
    assert dialog.open_path(transcript)
    assert dialog.review._player is None
    assert len(dialog.viewer.spans) == 2
    before = dialog.viewer.toPlainText()
    dialog.viewer.mark_time(3)
    assert dialog.viewer.toPlainText() == before
    dialog.content_search.setText("palabra clave")
    dialog._update_content_matches()
    assert len(dialog._content_matches) == 1
    dialog._review_time(1)
    assert dialog.review._player is None
    assert "primero" in dialog.review.status.text()
    dialog.close()


def test_real_qt_playback_seek_is_muted_and_does_not_autoplay(qt_application_lifetime, synthetic_video):
    from PySide6.QtMultimedia import QMediaPlayer
    from auralwarden.ui.media_review import MediaReviewPanel
    panel = MediaReviewPanel()
    assert panel.load_media(synthetic_video)
    deadline = time.monotonic() + 12
    while panel.duration == 0 and time.monotonic() < deadline:
        qt_application_lifetime.processEvents()
        time.sleep(0.02)
    assert panel.duration > 2.9
    assert panel._audio.isMuted()
    assert panel._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    frames = []
    panel._video_widget.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame) if frame.isValid() else None)
    assert panel.seek_session(1.2)
    assert panel._player.position() == pytest.approx(1200, abs=150)
    deadline = time.monotonic() + 3
    while not any(abs(frame.startTime() / 1_000_000 - 1.2) < 0.2 for frame in frames) and time.monotonic() < deadline:
        qt_application_lifetime.processEvents()
        time.sleep(0.02)
    assert frames, "Seeking must produce a visible frame, not just update the position counter"
    assert any(abs(frame.startTime() / 1_000_000 - 1.2) < 0.2 for frame in frames)
    assert panel._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    assert not panel.seek_session(99)
    panel.reset()
    assert panel._player.source().isEmpty()
    panel.close()


def test_clicking_a_fragment_opens_associated_video_at_its_time(qt_application_lifetime, synthetic_video, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from auralwarden.ui.management_dialogs import TranscriptLibraryDialog
    session = tmp_path / "session"
    recordings, transcripts = session / "recordings", session / "transcripts"
    recordings.mkdir(parents=True)
    transcripts.mkdir()
    video = recordings / "2026 - Video completo.mp4"
    shutil.copyfile(synthetic_video, video)
    (session / "session.json").write_text('{"status":"stopped"}')
    transcript = transcripts / "class.json"
    transcript.write_text(json.dumps([{"elapsed_seconds": 1.2, "end_seconds": 1.8,
                                      "text": "Esta frase debe saltar al segundo indicado."}]))
    dialog = TranscriptLibraryDialog(session)
    assert dialog.open_path(transcript)
    dialog.show()
    qt_application_lifetime.processEvents()
    cursor = QTextCursor(dialog.viewer.document())
    cursor.setPosition(dialog.viewer.spans[0].start + 5)
    rectangle = dialog.viewer.cursorRect(cursor)
    QTest.mouseClick(dialog.viewer.viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
    assert dialog.review.source == video.resolve()
    deadline = time.monotonic() + 10
    while (dialog.review.duration == 0 or abs(dialog.review._player.position() - 1200) > 150) and time.monotonic() < deadline:
        qt_application_lifetime.processEvents()
        time.sleep(0.02)
    assert dialog.review._player.position() == pytest.approx(1200, abs=150)
    assert dialog.review._audio.isMuted()
    dialog.close()


def test_closing_review_cancels_export_and_waits_without_destroying_worker(qt_application_lifetime, tmp_path, monkeypatch):
    from auralwarden.ui import media_review as ui
    calls = []
    def export(*args, cancel, **kwargs):
        cancel.wait(3)
        calls.append("cancelled" if cancel.is_set() else "unexpected finish")
        raise InterruptedError("Exportación cancelada.")
    monkeypatch.setattr(ui, "export_interval", export)
    panel = ui.MediaReviewPanel()
    worker = ui.ExportWorker(tmp_path / "input.mp4", tmp_path / "output.mp4", 0, 1, panel)
    panel.worker = worker
    worker.finished.connect(panel._export_finished)
    worker.start()
    panel.shutdown(lambda: calls.append("closed"))
    deadline = time.monotonic() + 5
    while "closed" not in calls and time.monotonic() < deadline:
        qt_application_lifetime.processEvents()
        time.sleep(0.02)
    assert calls == ["cancelled", "closed"]
    assert panel.worker is None
    panel.close()


def test_full_recording_keeps_segment_clock_in_a_sidecar(synthetic_video, tmp_path):
    from auralwarden.video_clips import render_full_video_recording
    buffer = tmp_path / "buffer"
    buffer.mkdir()
    shutil.copyfile(synthetic_video, buffer / "segment-0.mp4")
    manifest = buffer / "segments.csv"
    manifest.write_text("segment-0.mp4,2,5\n", encoding="utf-8")
    recording = tmp_path / "full.mp4"
    render_full_video_recording(manifest, buffer, recording)
    index = media.load_timeline(recording)
    assert index.known and index.to_media(3) == 1
    assert recording.is_file() and manifest.is_file()
