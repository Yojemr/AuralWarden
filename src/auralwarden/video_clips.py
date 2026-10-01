from __future__ import annotations

import csv
import os
from io import StringIO
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from auralwarden.filenames import date_time_label, elapsed_label, readable_name, unique_path
from auralwarden.models import DetectionEvent
from auralwarden.paths import runtime_executable


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True, slots=True)
class VideoSegment:
    path: Path
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class CompletedVideoClip:
    event_id: str
    path: Path
    truncated: bool


@dataclass(frozen=True, slots=True)
class FailedVideoClip:
    event_id: str
    message: str


VideoClipOutcome = CompletedVideoClip | FailedVideoClip


@dataclass(slots=True)
class PendingVideoClip:
    detection: DetectionEvent
    target_end_seconds: float
    start_seconds: float


class VideoClipManager:
    """Builds MP4 evidence clips from a bounded rolling set of media segments."""

    def __init__(
        self,
        output_dir: Path,
        buffer_dir: Path,
        manifest_path: Path,
        pre_seconds: float,
        post_seconds: float,
        buffer_seconds: float,
        *,
        ffmpeg_path: str = "",
        retain_all_segments: bool = False,
        max_queued_clips: int = 8,
    ) -> None:
        self.output_dir = output_dir
        self.buffer_dir = buffer_dir
        self.manifest_path = manifest_path
        self.pre_seconds = max(0.0, pre_seconds)
        self.post_seconds = max(0.0, post_seconds)
        self.buffer_seconds = max(self.pre_seconds + 5.0, buffer_seconds)
        self.ffmpeg_path = ffmpeg_path
        self.retain_all_segments = retain_all_segments
        self._pending: dict[str, PendingVideoClip] = {}
        self._segments: list[VideoSegment] = []
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="AuralWardenVideoClip"
        )
        self._active: dict[
            str, tuple[Future[VideoClipOutcome], frozenset[Path]]
        ] = {}
        self._closed = False
        self.max_queued_clips = max(1, max_queued_clips)
        self.recovery_required = False
        self._manifest_identity: tuple[int, int] | None = None
        self._manifest_offset = 0

    def schedule(
        self, detection: DetectionEvent, captured_until_seconds: float
    ) -> list[VideoClipOutcome]:
        self._refresh_segments()
        outcomes = self._collect_finished()
        if len(self._pending) + len(self._active) >= self.max_queued_clips:
            return [*outcomes, FailedVideoClip(
                detection.event_id,
                "La cola de clips de vídeo está llena; la alerta se conserva, pero no se pudo añadir otro clip.",
            )]
        pending = PendingVideoClip(
            detection=replace(detection),
            target_end_seconds=detection.elapsed_seconds + self.post_seconds,
            start_seconds=max(0.0, detection.elapsed_seconds - self.pre_seconds),
        )
        self._pending[detection.event_id] = pending
        if self._ready(pending, captured_until_seconds):
            immediate = self._submit(detection.event_id, forced_truncated=False)
            if immediate is not None:
                outcomes.append(immediate)
        outcomes.extend(self._collect_finished())
        return outcomes

    def push(self, captured_until_seconds: float) -> list[VideoClipOutcome]:
        self._refresh_segments()
        completed = self._collect_finished()
        for event_id, pending in tuple(self._pending.items()):
            if self._ready(pending, captured_until_seconds):
                immediate = self._submit(event_id, forced_truncated=False)
                if immediate is not None:
                    completed.append(immediate)
        self._discard_expired(captured_until_seconds)
        completed.extend(self._collect_finished())
        return completed

    def flush(self) -> list[VideoClipOutcome]:
        if self._closed:
            return self._collect_finished()
        self._refresh_segments()
        outcomes = self._collect_finished()
        for event_id in tuple(self._pending):
            immediate = self._submit(event_id, forced_truncated=True)
            if immediate is not None:
                outcomes.append(immediate)
        self._executor.shutdown(wait=True)
        self._closed = True
        outcomes.extend(self._collect_finished())
        return outcomes

    def cleanup(self) -> None:
        if not self._closed:
            self._executor.shutdown(wait=True)
            self._closed = True
        self._collect_finished()
        for path in self.buffer_dir.glob("segment-*.ts"):
            path.unlink(missing_ok=True)
        for path in self.buffer_dir.glob("segments-*.csv"):
            path.unlink(missing_ok=True)
        for path in self.buffer_dir.glob("concat-*.ffconcat"):
            path.unlink(missing_ok=True)
        self.manifest_path.unlink(missing_ok=True)
        (self.buffer_dir / "segments.csv").unlink(missing_ok=True)
        for path in self.buffer_dir.glob("segments*.csv.tmp"):
            path.unlink(missing_ok=True)
        try:
            self.buffer_dir.rmdir()
        except OSError:
            pass

    def _ready(
        self, pending: PendingVideoClip, captured_until_seconds: float
    ) -> bool:
        if captured_until_seconds < pending.target_end_seconds:
            return False
        relevant = [segment for segment in self._segments
                    if segment.end_seconds > pending.start_seconds
                    and segment.start_seconds < pending.target_end_seconds]
        return (bool(relevant)
                and relevant[-1].end_seconds >= pending.target_end_seconds - 0.05
                and not any(right.start_seconds > left.end_seconds + 0.05
                            for left, right in zip(relevant, relevant[1:])))

    def _refresh_segments(self) -> None:
        if not self.manifest_path.is_file():
            return
        parsed: list[VideoSegment] = []
        try:
            with self.manifest_path.open("rb") as source:
                stat = os.fstat(source.fileno())
                identity = (stat.st_dev, stat.st_ino)
                append_only = identity == self._manifest_identity and stat.st_size >= self._manifest_offset
                if append_only:
                    source.seek(self._manifest_offset)
                else:
                    self._manifest_offset = 0
                data = source.read()
                complete = data.rfind(b"\n") + 1
                if not complete:
                    return
                self._manifest_offset += complete
                self._manifest_identity = identity
                for row in csv.reader(StringIO(data[:complete].decode("utf-8"))):
                    if len(row) < 3:
                        continue
                    path = self.buffer_dir / Path(row[0]).name
                    try:
                        start_seconds = float(row[1])
                        end_seconds = float(row[2])
                    except ValueError:
                        continue
                    if path.is_file() and path.stat().st_size > 0 and end_seconds > start_seconds:
                        parsed.append(VideoSegment(path, start_seconds, end_seconds))
        except (OSError, UnicodeError):
            return
        # A transient rewrite of FFmpeg's list must not forget closed segments.
        by_path = {item.path: item for item in self._segments if item.path.is_file()}
        by_path.update({item.path: item for item in parsed})
        self._segments = sorted(by_path.values(), key=lambda item: item.start_seconds)

    def _discard_expired(self, captured_until_seconds: float) -> None:
        cutoff = max(0.0, captured_until_seconds - self.buffer_seconds)
        if self._pending:
            earliest_needed = min(
                item.start_seconds
                for item in self._pending.values()
            )
            cutoff = min(cutoff, earliest_needed)
        retained: list[VideoSegment] = []
        protected = {
            path
            for _, paths in self._active.values()
            for path in paths
        }
        for segment in self._segments:
            if segment.end_seconds < cutoff and segment.path not in protected:
                if not self.retain_all_segments:
                    segment.path.unlink(missing_ok=True)
            else:
                retained.append(segment)
        self._segments = retained

    def _submit(
        self, event_id: str, forced_truncated: bool
    ) -> VideoClipOutcome | None:
        pending = self._pending.pop(event_id)
        detection = pending.detection
        requested_start = pending.start_seconds
        requested_end = pending.target_end_seconds
        segments = [
            segment
            for segment in self._segments
            if segment.end_seconds > requested_start
            and segment.start_seconds < requested_end
            and segment.path.is_file()
        ]
        if not segments:
            return FailedVideoClip(event_id, "No había segmentos de vídeo disponibles para la alerta.")

        future = self._executor.submit(
            self._render_pending,
            pending,
            tuple(segments),
            forced_truncated,
        )
        self._active[event_id] = (
            future,
            frozenset(segment.path for segment in segments),
        )
        return None

    def _collect_finished(self) -> list[VideoClipOutcome]:
        outcomes: list[VideoClipOutcome] = []
        for event_id, (future, _) in tuple(self._active.items()):
            if not future.done():
                continue
            self._active.pop(event_id)
            try:
                outcome = future.result()
                if isinstance(outcome, FailedVideoClip):
                    self.recovery_required = True
                outcomes.append(outcome)
            except Exception as exc:
                self.recovery_required = True
                outcomes.append(
                    FailedVideoClip(event_id, f"No se pudo crear el clip MP4: {exc}")
                )
        return outcomes

    def _render_pending(
        self,
        pending: PendingVideoClip,
        segments: tuple[VideoSegment, ...],
        forced_truncated: bool,
    ) -> VideoClipOutcome:
        detection = pending.detection
        event_id = detection.event_id
        requested_start = pending.start_seconds
        requested_end = pending.target_end_seconds

        available_start = segments[0].start_seconds
        available_end = segments[-1].end_seconds
        clip_start = max(requested_start, available_start)
        clip_end = min(requested_end, available_end)
        truncated = (
            forced_truncated
            or available_start > requested_start + 0.05
            or available_end < requested_end - 0.05
            or any(right.start_seconds > left.end_seconds + 0.05
                   for left, right in zip(segments, segments[1:]))
        )
        if clip_end <= clip_start:
            return FailedVideoClip(event_id, "El intervalo de vídeo disponible estaba vacío.")

        filename = (
            f"{date_time_label(detection.first_detected_at)} - Clip de video - "
            f"{readable_name(detection.phrase, 'Hotword')} - "
            f"{elapsed_label(detection.elapsed_seconds)}.mp4"
        )
        output_path = unique_path(self.output_dir / filename)
        concat_path = self.buffer_dir / f"concat-{detection.event_id[:12]}.ffconcat"
        try:
            self._write_concat_file(concat_path, segments)
            self._render_clip(
                concat_path,
                output_path,
                offset_seconds=max(0.0, clip_start - available_start),
                duration_seconds=clip_end - clip_start,
            )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            return FailedVideoClip(event_id, f"No se pudo crear el clip MP4: {exc}")
        finally:
            concat_path.unlink(missing_ok=True)
        return CompletedVideoClip(event_id, output_path, truncated)

    @staticmethod
    def _write_concat_file(
        path: Path, segments: list[VideoSegment] | tuple[VideoSegment, ...]
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["ffconcat version 1.0"]
        for segment in segments:
            normalized = segment.path.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{normalized}'")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _render_clip(
        self,
        concat_path: Path,
        output_path: Path,
        *,
        offset_seconds: float,
        duration_seconds: float,
    ) -> None:
        ffmpeg = self.ffmpeg_path or runtime_executable("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg no está disponible.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        common = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-ss",
            f"{offset_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
        ]
        copy_command = [
            *common,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            copy_command,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=60,
            check=False,
        )
        if (result.returncode == 0 and output_path.is_file()
                and output_path.stat().st_size > 0 and self._has_video_frame(ffmpeg, output_path)):
            return
        output_path.unlink(missing_ok=True)
        transcode_command = [
            *common,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        fallback = subprocess.run(
            transcode_command,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=120,
            check=False,
        )
        if (fallback.returncode != 0 or not output_path.is_file()
                or output_path.stat().st_size == 0 or not self._has_video_frame(ffmpeg, output_path)):
            detail = fallback.stderr.strip() or result.stderr.strip() or "FFmpeg terminó sin salida."
            raise RuntimeError(detail)

    @staticmethod
    def _has_video_frame(ffmpeg: str, path: Path) -> bool:
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-map", "0:v:0", "-frames:v", "1", "-an", "-progress", "pipe:1",
             "-nostats", "-f", "null", "-"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
            timeout=15, check=False,
        )
        return probe.returncode == 0 and any(
            line.startswith("frame=") and int(line.partition("=")[2].strip() or "0") > 0
            for line in probe.stdout.splitlines()
        )


def render_full_video_recording(
    manifest_path: Path,
    buffer_dir: Path,
    output_path: Path,
    *,
    ffmpeg_path: str = "",
) -> Path:
    segments = _read_video_segments(manifest_path, buffer_dir)
    if not segments:
        raise RuntimeError("No había segmentos de vídeo para guardar la grabación completa.")
    concat_path = buffer_dir / "full-recording.ffconcat"
    VideoClipManager._write_concat_file(concat_path, segments)
    ffmpeg = ffmpeg_path or runtime_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg no está disponible.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=900,
            check=False,
        )
    finally:
        concat_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg terminó sin generar el vídeo.")
    return output_path


def cleanup_video_buffer(buffer_dir: Path, manifest_path: Path) -> None:
    for pattern in ("segment-*.ts", "segments-*.csv", "segments*.csv.tmp", "concat-*.ffconcat"):
        for path in buffer_dir.glob(pattern):
            path.unlink(missing_ok=True)
    (buffer_dir / "full-recording.ffconcat").unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)
    try:
        buffer_dir.rmdir()
    except OSError:
        pass


def _read_video_segments(manifest_path: Path, buffer_dir: Path) -> list[VideoSegment]:
    if not manifest_path.is_file():
        return []
    parsed: list[VideoSegment] = []
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as source:
            for row in csv.reader(source):
                if len(row) < 3:
                    continue
                path = buffer_dir / Path(row[0]).name
                try:
                    start_seconds = float(row[1])
                    end_seconds = float(row[2])
                except ValueError:
                    continue
                if path.is_file() and path.stat().st_size > 0 and end_seconds > start_seconds:
                    parsed.append(VideoSegment(path, start_seconds, end_seconds))
    except (OSError, UnicodeError):
        return []
    return sorted(parsed, key=lambda item: item.start_seconds)
