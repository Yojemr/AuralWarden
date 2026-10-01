from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from auralwarden.audio import PcmChunk, PcmFormat, PcmRingBuffer, write_pcm_wav
from auralwarden.filenames import date_time_label, elapsed_label, readable_name, unique_path
from auralwarden.models import DetectionEvent

@dataclass(slots=True)
class PendingAudioClip:
    detection: DetectionEvent
    target_end_seconds: float
    captured_until_seconds: float
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class CompletedAudioClip:
    event_id: str
    path: Path
    truncated: bool


class AudioClipManager:
    """Creates WAV evidence clips from the RAM pre-roll and incoming post-roll."""

    def __init__(
        self,
        output_dir: Path,
        ring_buffer: PcmRingBuffer,
        pre_seconds: float,
        post_seconds: float,
    ) -> None:
        self.output_dir = output_dir
        self.ring_buffer = ring_buffer
        self.format: PcmFormat = ring_buffer.format
        self.pre_seconds = max(0.0, pre_seconds)
        self.post_seconds = max(0.0, post_seconds)
        self._pending: dict[str, PendingAudioClip] = {}

    def schedule(self, detection: DetectionEvent, captured_until_seconds: float) -> list[CompletedAudioClip]:
        start_seconds = max(0.0, detection.elapsed_seconds - self.pre_seconds)
        target_end = detection.elapsed_seconds + self.post_seconds
        data, truncated = self.ring_buffer.interval(
            start_seconds, min(captured_until_seconds, target_end), captured_until_seconds
        )
        pending = PendingAudioClip(
            detection=replace(detection),
            target_end_seconds=target_end,
            captured_until_seconds=min(captured_until_seconds, target_end),
            data=bytearray(data),
            truncated=truncated,
        )
        self._pending[detection.event_id] = pending
        if captured_until_seconds >= pending.target_end_seconds:
            return [self._finish(detection.event_id, truncated=False)]
        return []

    def push(self, chunk: PcmChunk) -> list[CompletedAudioClip]:
        completed: list[CompletedAudioClip] = []
        for event_id, pending in tuple(self._pending.items()):
            if chunk.start_seconds > pending.captured_until_seconds + 0.001:
                pending.truncated = True
            start = max(chunk.start_seconds, pending.captured_until_seconds)
            end = min(chunk.end_seconds, pending.target_end_seconds)
            if end > start:
                start_byte = self.format.bytes_for_seconds(start - chunk.start_seconds)
                end_byte = self.format.bytes_for_seconds(end - chunk.start_seconds)
                pending.data.extend(chunk.data[start_byte:end_byte])
                pending.captured_until_seconds = end
            if chunk.end_seconds >= pending.target_end_seconds:
                completed.append(self._finish(event_id, truncated=False))
        return completed

    def flush(self) -> list[CompletedAudioClip]:
        return [self._finish(event_id, truncated=True) for event_id in tuple(self._pending)]

    def _finish(self, event_id: str, truncated: bool) -> CompletedAudioClip:
        pending = self._pending.pop(event_id)
        detection = pending.detection
        filename = (
            f"{date_time_label(detection.first_detected_at)} - Clip de audio - "
            f"{readable_name(detection.phrase, 'Hotword')} - "
            f"{elapsed_label(detection.elapsed_seconds)}.wav"
        )
        path = unique_path(self.output_dir / filename)
        write_pcm_wav(path, bytes(pending.data), self.format)
        return CompletedAudioClip(event_id, path, truncated or pending.truncated)
