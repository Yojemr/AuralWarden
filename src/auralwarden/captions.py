from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, replace
from threading import Event
from typing import Any, Callable, Iterator, Protocol
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class CaptionCue:
    text: str
    start_seconds: float
    end_seconds: float
    language: str = ""
    source: str = "youtube_captions"
    clock_origin_seconds: float | None = None
    clock_origin_monotonic: float | None = None
    clock_epoch: int = 0


class CaptionSource(Protocol):
    def cues(self, stop_event: Event) -> Iterator[CaptionCue]: ...


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    url: str
    language: str
    automatic: bool
    format: str = "json3"
    protocol: str = ""


def is_youtube_source(source: str) -> bool:
    host = (urlparse(source.strip()).hostname or "").casefold()
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class YoutubeCaptionSource:
    """Best-effort polling of YouTube captions as an auxiliary detector."""

    def __init__(
        self,
        source: str,
        language: str = "es",
        *,
        poll_interval_seconds: float = 3.0,
        refresh_interval_seconds: float = 240.0,
        retry_initial_seconds: float = 5.0,
        retry_max_seconds: float = 60.0,
        unavailable_after_attempts: int = 5,
        resolver: Callable[[str, str], CaptionTrack | None] | None = None,
        fetcher: Callable[[str], bytes] | None = None,
        status_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.source = source
        self.language = language or "es"
        self.poll_interval_seconds = max(0.25, poll_interval_seconds)
        self.refresh_interval_seconds = max(15.0, refresh_interval_seconds)
        self.retry_initial_seconds = max(0.25, retry_initial_seconds)
        self.retry_max_seconds = max(
            self.retry_initial_seconds, retry_max_seconds
        )
        self.unavailable_after_attempts = max(2, unavailable_after_attempts)
        self._resolver = resolver or resolve_youtube_caption_track
        self._fetcher = fetcher or _fetch_bytes
        self._status_callback = status_callback
        self._last_status = ""
        self._seen_segments: set[str] = set()
        self._seen_segment_order: deque[str] = deque()
        self._last_media_sequence: int | None = None
        self._current_poll_interval = self.poll_interval_seconds
        self.last_error = ""
        self.track: CaptionTrack | None = None

    def cues(self, stop_event: Event) -> Iterator[CaptionCue]:
        seen: set[str] = set()
        seen_order: deque[str] = deque()
        initialized = False
        next_refresh = 0.0
        resolve_attempt = 0
        watermark = float("-inf")
        origin_seconds: float | None = None
        origin_monotonic: float | None = None
        epoch = 0
        while not stop_event.is_set():
            now = time.monotonic()
            if self.track is None and now >= next_refresh:
                resolve_attempt += 1
                resolution_error = ""
                try:
                    resolved = self._resolver(self.source, self.language)
                except Exception as exc:
                    resolved = None
                    resolution_error = str(exc)
                if resolved is not None:
                    self.track = resolved
                    self.last_error = ""
                    resolve_attempt = 0
                    next_refresh = now + self.refresh_interval_seconds
                    self._emit_track_ready(resolved)
                else:
                    self.track = None
                    self.last_error = resolution_error or "No hay subtítulos disponibles."
                    delay = self._retry_delay(resolve_attempt)
                    next_refresh = now + delay
                    if resolve_attempt == 1 and not resolution_error:
                        self._emit_status(
                            "caption_track_waiting",
                            "YouTube todavía no publica una pista compatible; AuralWarden seguirá esperando.",
                            attempt=resolve_attempt,
                            delay_seconds=delay,
                        )
                    elif resolve_attempt < self.unavailable_after_attempts:
                        self._emit_status(
                            "caption_track_retrying",
                            "La pista aún no está disponible; AuralWarden volverá a consultarla.",
                            attempt=resolve_attempt,
                            delay_seconds=delay,
                        )
                    else:
                        self._emit_status(
                            "caption_monitor_unavailable",
                            "YouTube no ofrece una pista compatible por ahora; AuralWarden continuará reintentando.",
                            attempt=resolve_attempt,
                            delay_seconds=delay,
                            retrying=True,
                        )
            elif self.track is not None and now >= next_refresh:
                try:
                    refreshed = self._resolver(self.source, self.language)
                except Exception as exc:
                    refreshed = None
                    self.last_error = str(exc)
                if refreshed is not None:
                    self.track = refreshed
                    self.last_error = ""
                    resolve_attempt = 0
                    next_refresh = now + self.refresh_interval_seconds
                    self._emit_track_ready(refreshed)
                else:
                    # Keep using the last URL while it remains valid. A temporary
                    # metadata failure must not discard a working caption track.
                    resolve_attempt = max(1, resolve_attempt + 1)
                    delay = self._retry_delay(resolve_attempt)
                    next_refresh = now + delay
                    self._emit_status(
                        "caption_track_retrying",
                        "No fue posible renovar la pista; se conservará mientras siga respondiendo.",
                        attempt=resolve_attempt,
                        delay_seconds=delay,
                    )
            if self.track is None:
                if stop_event.wait(self.poll_interval_seconds):
                    return
                continue
            try:
                cues = self._fetch_track(self.track)
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
                self.track = None
                resolve_attempt = max(1, resolve_attempt + 1)
                delay = self._retry_delay(resolve_attempt)
                next_refresh = time.monotonic() + delay
                self._emit_status(
                    "caption_track_retrying",
                    "Se perdió temporalmente la pista; AuralWarden buscará una nueva.",
                    attempt=resolve_attempt,
                    delay_seconds=delay,
                )
                if stop_event.wait(self.poll_interval_seconds):
                    return
                continue
            newest = max((cue.end_seconds for cue in cues), default=watermark)
            if newest < watermark - 120.0:
                initialized = False
                seen.clear()
                seen_order.clear()
                watermark = float("-inf")
                epoch += 1
            if not initialized and cues:
                origin_seconds = newest
                origin_monotonic = time.monotonic()
            for cue in cues:
                if cue.end_seconds < watermark - 30.0:
                    continue
                key = _cue_key(cue)
                if key in seen:
                    continue
                seen.add(key)
                seen_order.append(key)
                while len(seen_order) > 2_000:
                    seen.discard(seen_order.popleft())
                # The first response may contain captions from before monitoring began.
                if initialized:
                    yield replace(cue, clock_origin_seconds=origin_seconds,
                                  clock_origin_monotonic=origin_monotonic, clock_epoch=epoch)
            watermark = max(watermark, newest)
            initialized = initialized or bool(cues)
            if stop_event.wait(self._current_poll_interval):
                return

    def _fetch_track(self, track: CaptionTrack) -> list[CaptionCue]:
        if track.format == "json3":
            self._current_poll_interval = self.poll_interval_seconds
            return parse_json3_captions(self._fetcher(track.url), track.language)
        if track.format == "vtt" and track.protocol == "m3u8_native":
            playlist = self._fetcher(track.url)
            target_duration = parse_m3u8_target_duration(playlist)
            self._current_poll_interval = max(
                self.poll_interval_seconds,
                min(10.0, target_duration or self.poll_interval_seconds),
            )
            segments = parse_m3u8_segments(playlist, track.url)
            if segments:
                newest_sequence = segments[-1][0]
                if self._last_media_sequence is not None and newest_sequence < self._last_media_sequence:
                    self._seen_segments.clear()
                    self._seen_segment_order.clear()
                self._last_media_sequence = newest_sequence
            cues: list[CaptionCue] = []
            # Only the newest part is relevant when attaching to a live stream.
            # Subsequent polls use the media sequence as a stable deduplication key.
            for sequence, segment_url in segments[-8:]:
                segment_key = f"{track.language}|{sequence}"
                if segment_key in self._seen_segments:
                    continue
                payload = self._fetcher(segment_url)
                cues.extend(parse_webvtt_captions(payload, track.language))
                self._remember_segment(segment_key)
            return sorted(
                cues,
                key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.text),
            )
        if track.format == "vtt":
            self._current_poll_interval = self.poll_interval_seconds
            return parse_webvtt_captions(self._fetcher(track.url), track.language)
        raise ValueError(f"Formato de subtítulos no compatible: {track.format}")

    def _remember_segment(self, key: str) -> None:
        self._seen_segments.add(key)
        self._seen_segment_order.append(key)
        while len(self._seen_segment_order) > 2_000:
            self._seen_segments.discard(self._seen_segment_order.popleft())

    def _retry_delay(self, attempt: int) -> float:
        exponent = max(0, min(10, int(attempt) - 1))
        return min(
            self.retry_max_seconds,
            self.retry_initial_seconds * (2**exponent),
        )

    def _emit_track_ready(self, track: CaptionTrack) -> None:
        kind = "automáticos" if track.automatic else "del canal"
        self._emit_status(
            "caption_track_ready",
            f"Subtítulos {kind} disponibles en {track.language}.",
            language=track.language,
            automatic=track.automatic,
        )

    def _emit_status(self, code: str, message: str, **details: Any) -> None:
        fingerprint = f"{code}|{message}|{details}"
        if fingerprint == self._last_status:
            return
        self._last_status = fingerprint
        if self._status_callback is not None:
            self._status_callback(code, message, details)


def resolve_youtube_caption_track(source: str, language: str) -> CaptionTrack | None:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("El componente local yt-dlp no está disponible.") from exc
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 20,
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(source, download=False)
    if not isinstance(info, dict):
        return None
    requested = language.casefold()
    candidates: list[tuple[tuple[int, int, str], CaptionTrack]] = []
    for automatic, group_name in ((False, "subtitles"), (True, "automatic_captions")):
        group = info.get(group_name)
        if not isinstance(group, dict):
            continue
        for selected_language in group:
            if selected_language == "live_chat":
                continue
            formats = group.get(selected_language)
            if not isinstance(formats, list):
                continue
            ranked_formats: list[tuple[int, dict[str, Any]]] = []
            for item in formats:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                extension = str(item.get("ext") or "").casefold()
                protocol = str(item.get("protocol") or "").casefold()
                if extension == "json3":
                    format_rank = 0
                elif extension == "vtt" and protocol == "m3u8_native":
                    format_rank = 1
                elif extension == "vtt":
                    format_rank = 2
                else:
                    continue
                ranked_formats.append((format_rank, item))
            if not ranked_formats:
                continue
            format_rank, selected = min(ranked_formats, key=lambda item: item[0])
            normalized_language = str(selected_language).casefold()
            if normalized_language == requested:
                language_rank = 0
            elif normalized_language.startswith(requested + "-"):
                language_rank = 1
            elif requested.startswith(normalized_language + "-"):
                language_rank = 2
            elif normalized_language.startswith("es"):
                language_rank = 3
            else:
                language_rank = 4
            # Language relevance is more important than whether captions were
            # supplied by the channel or generated automatically.
            rank = (language_rank, format_rank, str(selected_language))
            candidates.append(
                (
                    rank,
                    CaptionTrack(
                        str(selected["url"]),
                        str(selected_language),
                        automatic,
                        str(selected.get("ext") or "").casefold(),
                        str(selected.get("protocol") or "").casefold(),
                    ),
                )
            )
    if not candidates:
        return None
    requested_candidates = [item for item in candidates if item[0][0] < 4]
    if requested_candidates:
        return min(requested_candidates, key=lambda item: item[0])[1]
    # Some YouTube live streams expose the only visible caption track under an
    # incorrect language key (observed as `en` for spoken Spanish). Using a sole
    # timed-text track is safer than declaring captions unavailable. If several
    # unrelated languages exist, do not guess.
    if len(candidates) == 1 and candidates[0][1].automatic:
        return candidates[0][1]
    return None


def parse_json3_captions(payload: bytes | str, language: str = "") -> list[CaptionCue]:
    if isinstance(payload, bytes):
        raw = json.loads(payload.decode("utf-8", errors="replace"))
    else:
        raw = json.loads(payload)
    cues: list[CaptionCue] = []
    events = raw.get("events", []) if isinstance(raw, dict) else []
    for event in events:
        if not isinstance(event, dict) or "segs" not in event:
            continue
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in event.get("segs", [])
            if isinstance(segment, dict)
        )
        text = " ".join(text.replace("\n", " ").split())
        if not text:
            continue
        start = max(0.0, float(event.get("tStartMs") or 0.0) / 1_000.0)
        duration = max(0.0, float(event.get("dDurationMs") or 0.0) / 1_000.0)
        cues.append(CaptionCue(text, start, start + duration, language))
    return sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.text))


def parse_m3u8_segments(
    payload: bytes | str,
    playlist_url: str,
) -> list[tuple[int, str]]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("La pista de subtítulos no contiene una lista M3U8 válida.")
    media_sequence = 0
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.partition(":")[2].strip())
            except ValueError:
                media_sequence = 0
            break
    segments: list[tuple[int, str]] = []
    for line in lines:
        if line.startswith("#"):
            continue
        segments.append((media_sequence + len(segments), urljoin(playlist_url, line)))
    return segments


def parse_m3u8_target_duration(payload: bytes | str) -> float | None:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    for line in text.splitlines():
        if not line.startswith("#EXT-X-TARGETDURATION:"):
            continue
        try:
            return max(0.25, float(line.partition(":")[2].strip()))
        except ValueError:
            return None
    return None


_VTT_TIMING = re.compile(
    r"^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})(?:\s|$)"
)
_VTT_TIMESTAMP_MAP = re.compile(
    r"LOCAL:(?P<local>[^,]+),MPEGTS:(?P<mpegts>\d+)", re.IGNORECASE
)


def parse_webvtt_captions(payload: bytes | str, language: str = "") -> list[CaptionCue]:
    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) else payload
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    timeline_offset = 0.0
    for line in lines[:10]:
        timestamp_map = _VTT_TIMESTAMP_MAP.search(line)
        if timestamp_map:
            timeline_offset = (
                int(timestamp_map.group("mpegts")) / 90_000.0
                - _parse_vtt_timestamp(timestamp_map.group("local"))
            )
            break
    cues: list[CaptionCue] = []
    index = 0
    while index < len(lines):
        timing = _VTT_TIMING.match(lines[index].strip())
        if timing is None:
            index += 1
            continue
        start = timeline_offset + _parse_vtt_timestamp(timing.group("start"))
        end = timeline_offset + _parse_vtt_timestamp(timing.group("end"))
        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index].strip())
            index += 1
        cue_text = " ".join(" ".join(cue_lines).split())
        cue_text = re.sub(r"<[^>]+>", "", cue_text).strip()
        if cue_text:
            cues.append(
                CaptionCue(
                    cue_text,
                    max(0.0, start),
                    max(max(0.0, start), end),
                    language,
                )
            )
    return sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.text))


def _parse_vtt_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        raise ValueError(f"Marca de tiempo WebVTT inválida: {value}")
    return int(hours) * 3_600.0 + int(minutes) * 60.0 + float(seconds)


def _cue_key(cue: CaptionCue) -> str:
    return f"{cue.start_seconds:.3f}|{cue.end_seconds:.3f}|{cue.text.casefold()}"


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 AuralWarden/0.5"})
    with urlopen(request, timeout=20) as response:
        return response.read()
