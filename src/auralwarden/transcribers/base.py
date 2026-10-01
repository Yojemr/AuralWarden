from __future__ import annotations

from collections import deque
from typing import Protocol

from auralwarden.audio import PcmFormat
from auralwarden.models import TranscriptEntry


class Transcriber(Protocol):
    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]: ...


class NullTranscriber:
    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]:
        return []


class ScriptedTranscriber:
    """Returns one predefined utterance for each transcription window."""

    def __init__(self, lines: list[tuple[str, str]]) -> None:
        self._lines = deque(lines)

    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]:
        if not self._lines:
            return []
        speaker, text = self._lines.popleft()
        duration = pcm_format.seconds_for_bytes(len(pcm))
        return [
            TranscriptEntry(
                elapsed_seconds=offset_seconds,
                end_seconds=offset_seconds + duration,
                speaker_id=speaker,
                text=text,
                confidence=0.99,
                source="scripted",
                second_pass=high_precision,
            )
        ]
