from __future__ import annotations

import importlib.util
import csv
from io import StringIO
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from io import BufferedIOBase
from pathlib import Path
from threading import Event, Thread, RLock
from typing import Any, BinaryIO, Callable
from urllib.parse import unquote, urlparse

from auralwarden.audio import PcmChunk, PcmFormat
from auralwarden.paths import runtime_executable


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CaptureError(RuntimeError):
    pass


@dataclass(slots=True)
class CaptureConfig:
    source: str
    quality: str = "audio_only,best"
    chunk_seconds: float = 1.0
    realtime_local_files: bool = False
    ffmpeg_path: str = ""
    pcm_format: PcmFormat = PcmFormat()
    video_segments_dir: Path | None = None
    video_segment_seconds: float = 2.0
    video_manifest_name: str = "segments.csv"
    video_segment_prefix: str = "segment"
    retain_all_video_segments: bool = False


@dataclass(frozen=True, slots=True)
class ReconnectConfig:
    enabled: bool = True
    max_attempts: int = 8
    initial_delay_seconds: float = 5.0
    max_delay_seconds: float = 60.0


def _local_source(source: str) -> Path | None:
    candidate = Path(source).expanduser()
    if candidate.exists():
        return candidate.resolve()
    parsed = urlparse(source)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)
    if parsed.scheme == "":
        return candidate.resolve() if candidate.exists() else None
    return None


def is_remote_source(source: str) -> bool:
    return _local_source(source) is None and bool(urlparse(source).scheme)


def is_direct_media_url(source: str) -> bool:
    parsed = urlparse(source.strip())
    suffix = Path(parsed.path).suffix.casefold()
    return parsed.scheme in {"http", "https"} and suffix in {
        ".aac",
        ".flac",
        ".m3u",
        ".m3u8",
        ".m4a",
        ".mp3",
        ".mpd",
        ".ogg",
        ".opus",
        ".pls",
        ".wav",
        ".webm",
    }


class FfmpegPcmCapture:
    """Yields mono 16 kHz PCM blocks from a local file or Streamlink source."""

    def __init__(self, config: CaptureConfig) -> None:
        self.config = config
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._stream_handle: BinaryIO | BufferedIOBase | None = None
        self._pump_thread: Thread | None = None
        self._pump_stop = Event()
        self._pump_error = ""
        self._stderr_thread: Thread | None = None
        self._stderr_tail = bytearray()
        self._stop_lock = RLock()

    def set_video_retention(self, retain_all: bool) -> None:
        self.config.retain_all_video_segments = retain_all

    @property
    def running(self) -> bool:
        return self._ffmpeg is not None and self._ffmpeg.poll() is None

    def _ffmpeg_executable(self) -> str:
        executable = self.config.ffmpeg_path or runtime_executable("ffmpeg")
        if not executable:
            raise CaptureError(
                "FFmpeg no está incluido junto a AuralWarden, en PATH ni en la configuración."
            )
        return executable

    def configure_video_buffer(
        self, directory: Path, *, segment_seconds: float = 2.0
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        self.config.video_segments_dir = directory.resolve()
        self.config.video_segment_seconds = max(1.0, min(10.0, segment_seconds))
        manifest = self.config.video_segments_dir / self.config.video_manifest_name
        return manifest

    @staticmethod
    def streamlink_available() -> bool:
        return importlib.util.find_spec("streamlink") is not None

    def chunks(self, stop_event: Event) -> Iterator[PcmChunk]:
        if stop_event.is_set() or self._pump_stop.is_set():
            return
        local = _local_source(self.config.source)
        direct_remote = False
        if local is None:
            if not self.streamlink_available():
                if is_direct_media_url(self.config.source):
                    direct_remote = True
                else:
                    raise CaptureError(
                        "La fuente remota requiere Streamlink. Instale el extra 'capture'."
                    )
            else:
                try:
                    self._stream_handle = self._open_streamlink()
                except CaptureError:
                    if not is_direct_media_url(self.config.source):
                        raise
                    direct_remote = True

        command = [self._ffmpeg_executable(), "-hide_banner", "-loglevel", "error"]
        if local is not None and self.config.realtime_local_files:
            command.append("-re")
        command.extend(
            [
                "-i",
                (
                    str(local)
                    if local is not None
                    else self.config.source
                    if direct_remote
                    else "pipe:0"
                ),
            ]
        )
        command.extend(
            [
                "-map",
                "0:a:0",
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ac",
                str(self.config.pcm_format.channels),
                "-ar",
                str(self.config.pcm_format.sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ]
        )
        if self.config.video_segments_dir is not None:
            directory = self.config.video_segments_dir
            manifest = directory / self.config.video_manifest_name
            command.extend(
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-f",
                    "segment",
                    "-segment_time",
                    f"{self.config.video_segment_seconds:.3f}",
                    "-segment_list",
                    str(manifest),
                    "-segment_list_type",
                    "csv",
                    "-segment_list_size",
                    "0",
                    "-reset_timestamps",
                    "1",
                    str(directory / f"{self.config.video_segment_prefix}-%06d.ts"),
                ]
            )
        with self._stop_lock:
            if stop_event.is_set() or self._pump_stop.is_set():
                self._stop_locked()
                return
            try:
                process = subprocess.Popen(
                    command,
                    stdin=(subprocess.PIPE if local is None and not direct_remote
                           else subprocess.DEVNULL),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=CREATE_NO_WINDOW,
                )
                self._ffmpeg = process
                self._start_stderr_drain()
                if local is None and not direct_remote:
                    self._start_stream_pump()
                stdout = process.stdout
            except Exception:
                self._stop_locked()
                raise
        if stdout is None:
            self.stop()
            raise CaptureError("FFmpeg no expuso audio PCM.")

        chunk_size = self.config.pcm_format.bytes_for_seconds(self.config.chunk_seconds)
        if chunk_size <= 0:
            self.stop()
            raise CaptureError("La duración de bloque configurada no es válida.")

        elapsed = 0.0
        pending = bytearray()
        finished_reading = False
        try:
            while not stop_event.is_set():
                try:
                    block = stdout.read(chunk_size - len(pending))
                except (OSError, ValueError):
                    if stop_event.is_set():
                        break
                    raise
                if not block:
                    break
                pending.extend(block)
                if len(pending) < chunk_size:
                    continue
                data = bytes(pending)
                pending.clear()
                duration = self.config.pcm_format.seconds_for_bytes(len(data))
                yield PcmChunk(data, elapsed, elapsed + duration)
                elapsed += duration
            if pending:
                data = bytes(pending)
                duration = self.config.pcm_format.seconds_for_bytes(len(data))
                yield PcmChunk(data, elapsed, elapsed + duration)
            finished_reading = True
        finally:
            stopped_by_user = stop_event.is_set()
            error = ""
            try:
                # If the consumer aborts while FFmpeg is still filling stdout,
                # waiting before terminating can deadlock on a full pipe.
                if finished_reading:
                    error = self._collect_error(stopped_by_user)
            finally:
                self.stop()
            if error:
                raise CaptureError(error)

    def _collect_error(self, stopped_by_user: bool) -> str:
        if stopped_by_user:
            return ""
        ffmpeg_error = ""
        process = self._ffmpeg
        if process is not None:
            code = process.wait(timeout=5)
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=2)
            if code != 0:
                ffmpeg_error = self._stderr_tail.decode("utf-8", errors="replace").strip() or f"FFmpeg terminó con código {code}."
        return ffmpeg_error or self._pump_error

    def _start_stderr_drain(self) -> None:
        self._stderr_tail = bytearray()
        if self._ffmpeg is None or self._ffmpeg.stderr is None:
            return
        stream = self._ffmpeg.stderr
        tail = self._stderr_tail

        def drain() -> None:
            try:
                while block := stream.read(4096):
                    tail.extend(block)
                    if len(tail) > 65_536:
                        del tail[:-65_536]
            except (OSError, ValueError):
                pass

        self._stderr_thread = Thread(target=drain, name="AuralWardenFfmpegLog", daemon=True)
        self._stderr_thread.start()

    def _open_streamlink(self):
        try:
            from streamlink import Streamlink
        except ImportError as exc:
            raise CaptureError("Streamlink no está instalado.") from exc
        session = Streamlink()
        session.set_option("stream-timeout", 30)
        session.set_option("ffmpeg-ffmpeg", self._ffmpeg_executable())
        try:
            streams = session.streams(self.config.source)
        except Exception as exc:
            raise CaptureError(f"Streamlink no pudo resolver la fuente: {exc}") from exc
        selected = None
        requested = [item.strip() for item in self.config.quality.split(",")]
        for quality in requested:
            if quality in streams:
                selected = streams[quality]
                break
        if selected is None:
            available = ", ".join(streams) or "ninguna"
            raise CaptureError(f"Calidad no disponible. Opciones: {available}")
        try:
            return selected.open()
        except Exception as exc:
            raise CaptureError(f"Streamlink no pudo abrir la fuente: {exc}") from exc

    def _start_stream_pump(self) -> None:
        if self._ffmpeg is None or self._ffmpeg.stdin is None or self._stream_handle is None:
            raise CaptureError("No fue posible construir la tubería Streamlink/FFmpeg.")
        self._pump_stop.clear()
        self._pump_error = ""
        source = self._stream_handle
        stdin = self._ffmpeg.stdin

        def pump() -> None:
            try:
                while not self._pump_stop.is_set():
                    data = source.read(64 * 1024)
                    if not data:
                        break
                    stdin.write(data)
                    stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                if not self._pump_stop.is_set():
                    self._pump_error = str(exc)
            finally:
                try:
                    stdin.close()
                except (OSError, ValueError):
                    pass

        self._pump_thread = Thread(target=pump, name="AuralWardenStreamPump", daemon=True)
        self._pump_thread.start()

    def stop(self) -> None:
        with self._stop_lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._pump_stop.set()
        if self._stream_handle is not None:
            try:
                self._stream_handle.close()
            except OSError:
                pass
        process = self._ffmpeg
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if self._pump_thread is not None and self._pump_thread.is_alive():
            self._pump_thread.join(timeout=3)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2)
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
        self._ffmpeg = None
        self._stream_handle = None
        self._pump_thread = None
        self._stderr_thread = None


class ReconnectingCapture:
    """Keeps a remote capture alive across recoverable Streamlink/FFmpeg failures."""

    def __init__(
        self,
        factory: Callable[[], FfmpegPcmCapture],
        policy: ReconnectConfig,
    ) -> None:
        self.factory = factory
        self.policy = policy
        self._active: FfmpegPcmCapture | None = None
        self._status_callback: Callable[[str, dict[str, Any]], None] | None = None
        self._video_dir: Path | None = None
        self._video_segment_seconds = 2.0
        self._master_manifest: Path | None = None
        self._manifest_rows: dict[str, tuple[float, float]] = {}
        self._manifest_versions: dict[Path, tuple[int, int]] = {}
        self._manifest_offsets: dict[Path, tuple[tuple[int, int], int]] = {}
        self._retain_all_video = False

    def set_video_retention(self, retain_all: bool) -> None:
        self._retain_all_video = retain_all

    def set_status_callback(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        self._status_callback = callback

    def configure_video_buffer(
        self, directory: Path, *, segment_seconds: float = 2.0
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        self._video_dir = directory.resolve()
        self._video_segment_seconds = max(1.0, min(10.0, segment_seconds))
        self._master_manifest = self._video_dir / "segments.csv"
        return self._master_manifest

    def chunks(self, stop_event: Event) -> Iterator[PcmChunk]:
        timeline_offset = 0.0
        retry_count = 0
        ever_received_audio = False
        attempt_index = 0
        while not stop_event.is_set():
            attempt_index += 1
            capture = self.factory()
            self._active = capture
            retention = getattr(capture, "set_video_retention", None)
            if callable(retention):
                retention(False)
            attempt_offset = timeline_offset
            attempt_manifest: Path | None = None
            if self._video_dir is not None:
                capture.config.video_manifest_name = f"segments-{attempt_index:04d}.csv"
                capture.config.video_segment_prefix = f"segment-{attempt_index:04d}"
                attempt_manifest = capture.configure_video_buffer(
                    self._video_dir,
                    segment_seconds=self._video_segment_seconds,
                )
            received_this_attempt = False
            try:
                for chunk in capture.chunks(stop_event):
                    if stop_event.is_set():
                        return
                    if not received_this_attempt:
                        self._emit(
                            "connected",
                            attempt=retry_count,
                            message=(
                                "El directo volvió a estar disponible."
                                if ever_received_audio
                                else "El directo está disponible."
                            ),
                        )
                    received_this_attempt = True
                    ever_received_audio = True
                    adjusted = PcmChunk(
                        chunk.data,
                        timeline_offset + chunk.start_seconds,
                        timeline_offset + chunk.end_seconds,
                    )
                    if attempt_manifest is not None:
                        self._merge_video_manifest(attempt_manifest, timeline_offset)
                    yield adjusted
                if attempt_manifest is not None:
                    self._merge_video_manifest(attempt_manifest, timeline_offset)
                if stop_event.is_set():
                    return
                if received_this_attempt:
                    timeline_offset = adjusted.end_seconds
                    self._emit("ended", message="El directo finalizó correctamente.")
                    return
                error = CaptureError("La fuente terminó sin entregar audio.")
            except Exception as exc:
                if stop_event.is_set():
                    return
                if received_this_attempt:
                    timeline_offset = adjusted.end_seconds
                error = exc
            finally:
                capture.stop()
                if attempt_manifest is not None:
                    self._merge_video_manifest(attempt_manifest, attempt_offset)
                self._active = None

            if not self.policy.enabled:
                raise error
            retry_count += 1
            if self.policy.max_attempts > 0 and retry_count > self.policy.max_attempts:
                raise CaptureError(
                    f"Se agotaron {self.policy.max_attempts} intentos de conexión. Último error: {error}"
                ) from error
            delay = min(
                max(0.01, self.policy.initial_delay_seconds) * (2 ** min(30, retry_count - 1)),
                max(0.01, self.policy.max_delay_seconds),
            )
            phase = "reconnecting" if ever_received_audio else "waiting"
            self._emit(
                phase,
                attempt=retry_count,
                delay_seconds=delay,
                message=str(error),
            )
            if stop_event.wait(delay):
                return

    def stop(self) -> None:
        active = self._active
        if active is not None:
            active.stop()

    def _emit(self, phase: str, **payload: Any) -> None:
        callback = self._status_callback
        if callback is not None:
            callback(phase, payload)

    def _merge_video_manifest(self, manifest: Path, offset: float) -> None:
        if self._master_manifest is None or not manifest.is_file():
            return
        try:
            stat = manifest.stat()
            version = (stat.st_mtime_ns, stat.st_size)
            if self._manifest_versions.get(manifest) == version:
                return
            updated_rows = dict(self._manifest_rows)
            new_rows: list[tuple[str, float, float]] = []
            with manifest.open("rb") as source:
                stat = os.fstat(source.fileno())
                identity = (stat.st_dev, stat.st_ino)
                previous_identity, previous_offset = self._manifest_offsets.get(manifest, (None, 0))
                position = previous_offset if identity == previous_identity and stat.st_size >= previous_offset else 0
                source.seek(position)
                data = source.read()
                complete = data.rfind(b"\n") + 1
                for row in csv.reader(StringIO(data[:complete].decode("utf-8"))):
                    if len(row) < 3:
                        continue
                    try:
                        start = offset + float(row[1])
                        end = offset + float(row[2])
                    except ValueError:
                        continue
                    name = Path(row[0]).name
                    if (manifest.parent / name).is_file():
                        if name not in self._manifest_rows:
                            new_rows.append((name, start, end))
                        updated_rows[name] = (start, end)
            # Append-only journals avoid Windows replacement failures while a
            # reader is inspecting a manifest. Only new complete rows are read.
            with self._master_manifest.open("a", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                for name, start, end in new_rows:
                    writer.writerow((name, f"{start:.6f}", f"{end:.6f}"))
            if self._retain_all_video:
                newest_end = max((end for _, end in updated_rows.values()), default=0.0)
                updated_rows = {name: interval for name, interval in updated_rows.items()
                                if interval[1] >= newest_end - 400.0}
            else:
                updated_rows = {name: interval for name, interval in updated_rows.items()
                                if (manifest.parent / name).is_file()}
            self._manifest_rows = updated_rows
            self._manifest_versions = {manifest: version}
            self._manifest_offsets = {manifest: (identity, position + complete)}
        except (OSError, UnicodeError):
            return


class MemoryPcmCapture:
    """Deterministic PCM source used by tests and the local simulation."""

    def __init__(
        self,
        duration_seconds: float,
        chunk_seconds: float = 1.0,
        pcm_format: PcmFormat | None = None,
        realtime: bool = False,
    ) -> None:
        self.format = pcm_format or PcmFormat()
        self.duration_seconds = max(0.0, duration_seconds)
        self.chunk_seconds = max(0.05, chunk_seconds)
        self.realtime = realtime

    def chunks(self, stop_event: Event) -> Iterator[PcmChunk]:
        elapsed = 0.0
        while elapsed < self.duration_seconds and not stop_event.is_set():
            duration = min(self.chunk_seconds, self.duration_seconds - elapsed)
            data = bytes(self.format.bytes_for_seconds(duration))
            actual = self.format.seconds_for_bytes(len(data))
            yield PcmChunk(data, elapsed, elapsed + actual)
            elapsed += actual
            if self.realtime and stop_event.wait(actual):
                break

    def stop(self) -> None:
        return
