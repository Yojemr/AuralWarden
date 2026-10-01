import shutil
import subprocess
import wave
import sys
from pathlib import Path
from threading import Event

import pytest

from auralwarden.audio import PcmChunk
from auralwarden.capture import (
    CaptureConfig,
    CaptureError,
    FfmpegPcmCapture,
    is_direct_media_url,
    ReconnectConfig,
    ReconnectingCapture,
)


def test_stderr_is_drained_without_blocking_pcm_and_keeps_bounded_tail():
    capture = FfmpegPcmCapture(CaptureConfig("unused"))
    capture._ffmpeg = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.buffer.write(b'x'*200000); sys.stderr.flush(); sys.stdout.buffer.write(b'pcm'); sys.stdout.flush()"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    process = capture._ffmpeg
    capture._start_stderr_drain()
    try:
        process.wait(timeout=10)
        assert process.stdout.read() == b"pcm"
        capture._stderr_thread.join(timeout=2)
        assert len(capture._stderr_tail) == 65_536
    finally:
        capture.stop()


def test_direct_radio_and_manifest_urls_are_recognized() -> None:
    assert is_direct_media_url("https://radio.example/live.mp3?token=abc")
    assert is_direct_media_url("https://video.example/channel/playlist.m3u8")
    assert is_direct_media_url("https://video.example/manifest.mpd")
    assert not is_direct_media_url("https://example.com/station")


def create_test_video(path: Path, duration_seconds: int = 8) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            str(duration_seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "10",
            "-keyint_min",
            "10",
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_ffmpeg_converts_local_wav_to_mono_16khz(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        audio.writeframes(bytes(48_000 * 2 * 2))

    capture = FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.25))
    chunks = list(capture.chunks(Event()))
    assert chunks
    assert abs(chunks[-1].end_seconds - 1.0) < 0.01
    assert sum(len(chunk.data) for chunk in chunks) == 16_000 * 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_ffmpeg_stops_cleanly_when_consumer_closes_early(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(bytes(16_000 * 2 * 10))

    capture = FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.25))
    chunks = capture.chunks(Event())
    next(chunks)
    chunks.close()

    assert not capture.running


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_ffmpeg_capture_creates_video_segment_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    create_test_video(source, 6)
    buffer_dir = tmp_path / "video-buffer"
    capture = FfmpegPcmCapture(CaptureConfig(str(source), chunk_seconds=0.5))
    manifest = capture.configure_video_buffer(buffer_dir, segment_seconds=2)

    chunks = list(capture.chunks(Event()))

    assert chunks[-1].end_seconds >= 5.9
    assert manifest.is_file()
    assert len(list(buffer_dir.glob("segment-*.ts"))) >= 2


class ScriptedCapture:
    def __init__(self, script: list[PcmChunk | Exception]) -> None:
        self.script = script
        self.stopped = False

    def chunks(self, stop_event: Event):
        for item in self.script:
            if stop_event.is_set():
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def stop(self) -> None:
        self.stopped = True


def test_remote_capture_waits_then_connects_and_ends_cleanly() -> None:
    attempts = iter(
        [
            ScriptedCapture([CaptureError("El directo todavía no inició")]),
            ScriptedCapture([PcmChunk(b"\x00\x00", 0.0, 1.0)]),
        ]
    )
    statuses: list[str] = []
    capture = ReconnectingCapture(
        lambda: next(attempts),
        ReconnectConfig(initial_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    capture.set_status_callback(lambda phase, _payload: statuses.append(phase))

    chunks = list(capture.chunks(Event()))

    assert [(item.start_seconds, item.end_seconds) for item in chunks] == [(0.0, 1.0)]
    assert statuses == ["waiting", "connected", "ended"]


def test_remote_capture_keeps_timeline_after_interruption() -> None:
    attempts = iter(
        [
            ScriptedCapture(
                [
                    PcmChunk(b"\x00\x00", 0.0, 1.0),
                    CaptureError("conexión interrumpida"),
                ]
            ),
            ScriptedCapture([PcmChunk(b"\x00\x00", 0.0, 1.0)]),
        ]
    )
    statuses: list[str] = []
    capture = ReconnectingCapture(
        lambda: next(attempts),
        ReconnectConfig(initial_delay_seconds=0.01, max_delay_seconds=0.01),
    )
    capture.set_status_callback(lambda phase, _payload: statuses.append(phase))

    chunks = list(capture.chunks(Event()))

    assert [(item.start_seconds, item.end_seconds) for item in chunks] == [
        (0.0, 1.0),
        (1.0, 2.0),
    ]
    assert "reconnecting" in statuses


def test_remote_capture_stops_after_configured_limit() -> None:
    capture = ReconnectingCapture(
        lambda: ScriptedCapture([CaptureError("sin señal")]),
        ReconnectConfig(
            max_attempts=2,
            initial_delay_seconds=0.01,
            max_delay_seconds=0.01,
        ),
    )

    with pytest.raises(CaptureError, match="Se agotaron 2 intentos"):
        list(capture.chunks(Event()))


def test_reconnected_video_manifests_keep_one_global_timeline(tmp_path: Path) -> None:
    capture = ReconnectingCapture(
        lambda: ScriptedCapture([]),
        ReconnectConfig(),
    )
    master = capture.configure_video_buffer(tmp_path)
    first = tmp_path / "segments-0001.csv"
    second = tmp_path / "segments-0002.csv"
    first.write_text("segment-0001-000000.ts,0.0,2.0\n", encoding="utf-8")
    second.write_text("segment-0002-000000.ts,0.0,2.0\n", encoding="utf-8")
    (tmp_path / "segment-0001-000000.ts").write_bytes(b"synthetic")
    (tmp_path / "segment-0002-000000.ts").write_bytes(b"synthetic")

    capture._merge_video_manifest(first, 0.0)
    capture._merge_video_manifest(second, 2.0)

    text = master.read_text(encoding="utf-8")
    assert "segment-0001-000000.ts,0.000000,2.000000" in text
    assert "segment-0002-000000.ts,2.000000,4.000000" in text
