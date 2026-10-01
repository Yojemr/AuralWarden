from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from auralwarden.audio import PcmFormat
from auralwarden.models import TranscriptEntry


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    start_seconds: float
    end_seconds: float
    speaker_id: str
    confidence: float | None = None


class Diarizer(Protocol):
    def assign(
        self,
        entries: list[TranscriptEntry],
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
    ) -> list[TranscriptEntry]: ...


class NullDiarizer:
    def assign(
        self,
        entries: list[TranscriptEntry],
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
    ) -> list[TranscriptEntry]:
        return entries
