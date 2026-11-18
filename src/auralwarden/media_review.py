from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from auralwarden.paths import runtime_executable

MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".flac", ".ogg"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def finite_time(value: float) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("El tiempo no es válido.") from exc
    if not math.isfinite(result) or abs(result) > 366 * 86400:
        raise ValueError("El tiempo está fuera del rango permitido.")
    return result


def parse_time(value: str) -> float:
    match = re.fullmatch(r"\s*(\d{1,5}):([0-5]\d):([0-5]\d(?:[.,]\d{1,3})?)\s*", value)
    if not match:
        raise ValueError("Usa HH:MM:SS o HH:MM:SS.mmm.")
    hours, minutes, seconds = match.groups()
    return finite_time(int(hours) * 3600 + int(minutes) * 60 + float(seconds.replace(",", ".")))


def format_time(value: float) -> str:
    milliseconds = max(0, round(finite_time(value) * 1000))
    seconds, fraction = divmod(milliseconds, 1000)
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}.{fraction:03d}"


@dataclass(frozen=True)
class TimelinePart:
    session_start: float
    session_end: float
    media_start: float
    media_end: float


@dataclass(frozen=True)
class MediaTimeline:
    parts: tuple[TimelinePart, ...] = ()
    known: bool = False

    def to_media(self, seconds: float, shift: float = 0) -> float:
        value = finite_time(seconds) - finite_time(shift)
        if not self.parts:
            if value < 0:
                raise ValueError("Ese instante es anterior al inicio de la grabación.")
            return value
        for part in self.parts:
            if part.session_start <= value < part.session_end:
                return part.media_start + value - part.session_start
        if abs(value - self.parts[-1].session_end) < 0.001:
            return self.parts[-1].media_end
        raise ValueError("No hay vídeo grabado para ese instante; puede pertenecer a una interrupción.")

    def to_session(self, seconds: float, shift: float = 0) -> float:
        value = finite_time(seconds)
        if not self.parts:
            return value + finite_time(shift)
        for part in self.parts:
            if part.media_start <= value < part.media_end:
                return part.session_start + value - part.media_start + finite_time(shift)
        if abs(value - self.parts[-1].media_end) < 0.05:
            return self.parts[-1].session_end + finite_time(shift)
        raise ValueError("El instante está fuera del índice temporal.")

    def interval(self, start: float, end: float, shift: float = 0) -> tuple[float, float]:
        start, end = finite_time(start), finite_time(end)
        if start < 0 or end <= start:
            raise ValueError("El final debe ser posterior al inicio y los tiempos no pueden ser negativos.")
        first = self.to_media(start, shift)
        endpoint = next((part for part in self.parts if abs(part.session_end - (end - shift)) < 0.001), None)
        last = endpoint.media_end if endpoint is not None else self.to_media(end, shift)
        if abs((last - first) - (end - start)) > 0.05:
            raise ValueError("El intervalo contiene una interrupción sin grabación. Elige un tramo continuo.")
        return first, last


def timeline_path(media: Path) -> Path:
    return media.with_suffix(media.suffix + ".timeline.json")


def load_timeline(media: Path) -> MediaTimeline:
    path = timeline_path(media)
    if not path.exists():
        return MediaTimeline()
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("El índice temporal no es válido.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("parts"), list):
        raise ValueError("El índice temporal tiene un formato no compatible.")
    stat = media.stat()
    if raw.get("media_size") != stat.st_size or raw.get("media_mtime_ns") != stat.st_mtime_ns:
        raise ValueError("El archivo cambió desde que se guardó su índice temporal; no se asume una sincronización válida.")
    if not 1 <= len(raw["parts"]) <= 50_000:
        raise ValueError("El índice temporal está vacío o supera su límite.")
    parts = []
    previous_session, previous_media = -1.0, 0.0
    for item in raw["parts"]:
        if not isinstance(item, dict):
            raise ValueError("Hay un tramo temporal no válido.")
        try:
            part = TimelinePart(*(finite_time(item[key]) for key in
                                  ("session_start", "session_end", "media_start", "media_end")))
        except KeyError as exc:
            raise ValueError("El índice temporal está incompleto.") from exc
        if (part.session_start < 0 or part.session_start < previous_session - 0.001
                or part.session_end <= part.session_start or part.media_end <= part.media_start
                or abs(part.media_start - previous_media) > 0.01
                or abs((part.session_end - part.session_start) - (part.media_end - part.media_start)) > 0.01):
            raise ValueError("El índice temporal contiene tiempos incoherentes.")
        parts.append(part)
        previous_session, previous_media = part.session_end, part.media_end
    return MediaTimeline(tuple(parts), True)


def save_timeline(media: Path, ranges) -> None:
    parts, cursor = [], 0.0
    for start, end in ranges:
        duration = end - start
        if parts and abs(parts[-1]["session_end"] - start) <= 0.000001:
            parts[-1]["session_end"] = end
            parts[-1]["media_end"] = cursor + duration
        else:
            parts.append({"session_start": start, "session_end": end,
                          "media_start": cursor, "media_end": cursor + duration})
        cursor += duration
    # Exclusive creation preserves any existing sidecar, including user-created data.
    with timeline_path(media).open("x", encoding="utf-8") as output:
        stat = media.stat()
        json.dump({"schema": 1, "media_size": stat.st_size, "media_mtime_ns": stat.st_mtime_ns,
                   "parts": parts}, output, ensure_ascii=False)


def discover_session_media(transcript: Path) -> Path | None:
    session = transcript.parent.parent if transcript.parent.name.casefold() == "transcripts" else transcript.parent
    metadata = session / "session.json"
    folder = session / "recordings"
    if not metadata.is_file() or metadata.is_symlink() or metadata.stat().st_size > 1024 * 1024:
        return None
    try:
        raw = json.loads(metadata.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or raw.get("status") not in {"stopped", "failed"}:
            return None
    except (OSError, ValueError):
        return None
    if (not folder.is_dir() or folder.is_symlink()
            or getattr(folder.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400):
        return None
    candidates = []
    for path in folder.iterdir():
        if path.suffix.casefold() in MEDIA_EXTENSIONS and path.is_file() and not path.is_symlink():
            candidates.append(path)
            if len(candidates) > 1000:
                return None
    videos = [path for path in candidates if "video completo" in path.stem.casefold()]
    audios = [path for path in candidates if "audio completo" in path.stem.casefold()]
    preferred = videos or audios
    return preferred[0] if len(preferred) == 1 else None


def validate_media(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.suffix.casefold() not in MEDIA_EXTENSIONS:
        raise ValueError("Selecciona un archivo de vídeo o audio local compatible, no un enlace ni una lista de reproducción.")
    return path


def probe_media(path: Path) -> tuple[float, bool]:
    path = validate_media(path)
    try:
        import av
    except ImportError:
        av = None
    if av is not None:
        def reject_nested(*_):
            raise ValueError("No se abren referencias auxiliares desde una grabación.")
        try:
            with path.open("rb") as input_file, av.open(input_file, mode="r", timeout=(5, 5),
                    options={"protocol_whitelist": "file,pipe", "probesize": "5000000", "analyzeduration": "5000000"},
                    io_open=reject_nested) as container:
                formats = set(container.format.name.split(","))
                if not formats.intersection({"mov", "mp4", "matroska", "webm", "wav", "mp3", "flac", "ogg", "aac"}):
                    raise ValueError("El archivo no es una grabación audiovisual autónoma compatible.")
                duration = container.duration / av.time_base if container.duration is not None else max(
                    (float(stream.duration * stream.time_base) for stream in container.streams
                     if stream.duration is not None and stream.time_base is not None), default=0)
                video = any(stream.type == "video" and not stream.disposition & av.stream.Disposition.attached_pic
                            for stream in container.streams)
                audio = any(stream.type == "audio" for stream in container.streams)
                duration = finite_time(duration)
                if duration <= 0 or not (video or audio):
                    raise ValueError("El archivo no contiene una duración o pistas válidas.")
                return duration, video
        except (OSError, ValueError, av.error.FFmpegError) as exc:
            raise ValueError("No se pudieron leer la duración y las pistas de la grabación local.") from exc
    probe = runtime_executable("ffprobe")
    if not probe:
        raise RuntimeError("El lector multimedia no está disponible; utiliza la carpeta portable completa.")
    result = subprocess.run([probe, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
        capture_output=True, timeout=20, creationflags=NO_WINDOW, check=False)
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError("No se pudo leer la duración y las pistas del archivo local.")
    try:
        raw = json.loads(result.stdout)
        duration = finite_time(raw["format"]["duration"])
        streams = raw["streams"]
        has_video = any(item.get("codec_type") == "video" for item in streams)
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("El archivo no tiene una duración válida.") from exc
    if duration <= 0 or not (has_video or has_audio):
        raise ValueError("El archivo no contiene pistas reproducibles.")
    return duration, has_video


def _identity(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def export_interval(source: Path, destination: Path, start: float, end: float, *, cancel: Event | None = None,
                    session_start: float | None = None) -> Path:
    source = validate_media(source)
    destination = destination.expanduser().absolute()
    start, end = finite_time(start), finite_time(end)
    if session_start is not None:
        session_start = finite_time(session_start)
        if session_start < 0:
            raise ValueError("El inicio de sesión no es válido.")
    if start < 0 or end <= start:
        raise ValueError("El intervalo no es válido.")
    if destination.exists() or destination.is_symlink() or destination.resolve() == source:
        raise ValueError("No se reemplazan archivos existentes ni la grabación original. Elige otro nombre.")
    cancel = cancel or Event()
    if cancel.is_set():
        raise InterruptedError("Exportación cancelada.")
    initial = _identity(source)
    duration, video = probe_media(source)
    if end > duration + 0.05:
        raise ValueError("El intervalo supera la duración de la grabación.")
    if destination.suffix.casefold() != (".mp4" if video else ".wav"):
        raise ValueError("Usa MP4 para vídeo o WAV para una grabación solo de audio.")
    ffmpeg = runtime_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg no está disponible.")
    if cancel.is_set():
        raise InterruptedError("Exportación cancelada.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".auralwarden-export-", dir=destination.parent) as folder:
        temporary = Path(folder) / ("clip" + destination.suffix)
        encoding = (["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "23", "-threads", "2", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
                    if video else ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le"])
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-protocol_whitelist", "file,pipe", "-threads", "2", "-filter_threads", "1",
            "-ss", f"{start:.6f}", "-i", str(source),
            "-t", f"{end - start:.6f}", "-map_metadata", "-1", *encoding, str(temporary)]
        with (Path(folder) / "ffmpeg.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log, creationflags=NO_WINDOW)
            deadline = time.monotonic() + max(60, min(7200, 60 + (end - start) * 3))
            try:
                while process.poll() is None:
                    if cancel.wait(0.1):
                        raise InterruptedError("Exportación cancelada.")
                    if time.monotonic() > deadline:
                        raise TimeoutError("La exportación superó su tiempo máximo; el original se conserva.")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(5)
        if cancel.is_set():
            raise InterruptedError("Exportación cancelada.")
        if process.returncode or not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("FFmpeg no pudo generar el clip. La grabación original se conserva.")
        if initial != _identity(source):
            raise ValueError("La grabación cambió durante la exportación. Espera a que termine de guardarse.")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise ValueError("El destino apareció durante la exportación; no se reemplazó.")
        except OSError:
            # Filesystems without hard links still get exclusive, non-overwriting creation.
            created = False
            try:
                with destination.open("xb") as output, temporary.open("rb") as input_file:
                    created = True
                    while block := input_file.read(1024 * 1024):
                        if cancel.is_set():
                            raise InterruptedError("Exportación cancelada.")
                        output.write(block)
            except BaseException:
                if created:
                    destination.unlink(missing_ok=True)
                raise
    if session_start is not None:
        try:
            save_timeline(destination, [(session_start, session_start + end - start)])
        except OSError:
            pass
    return destination
