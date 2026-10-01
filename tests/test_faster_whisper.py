from __future__ import annotations

from dataclasses import dataclass

import pytest

from auralwarden.audio import PcmFormat
from auralwarden.transcribers.faster_whisper import (
    FasterWhisperConfig,
    FasterWhisperTranscriber,
)


pytest.importorskip("numpy")


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class FakeSegment:
    text: str = " Necesito ayuda"
    start: float = 0.25
    end: float = 1.5
    avg_logprob: float = -0.2
    no_speech_prob: float = 0.1
    words: tuple[FakeWord, ...] = (
        FakeWord(" Necesito", 0.25, 0.8, 0.8),
        FakeWord(" ayuda", 0.8, 1.5, 0.95),
    )


class FakeModel:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return iter([FakeSegment()]), object()


def test_adapter_preserves_guidance_and_uses_neutral_vad_verification() -> None:
    transcriber = FasterWhisperTranscriber(
        FasterWhisperConfig(
            hotwords=["ayuda"],
            vocabulary=["VocabloSintetico"],
            initial_prompt="Conversación de videojuego.",
        )
    )
    model = FakeModel()
    transcriber._model = model
    pcm_format = PcmFormat()
    pcm = bytes(pcm_format.bytes_for_seconds(2))

    entries = transcriber.transcribe(pcm, pcm_format, 10)
    refined = transcriber.transcribe_verification(pcm, pcm_format, 10)

    assert entries[0].words[1].text.strip() == "ayuda"
    assert entries[0].words[1].start_seconds == 10.8
    assert entries[0].words[1].probability == 0.95
    assert model.calls[0]["vad_filter"] is True
    assert model.calls[1]["vad_filter"] is True
    assert model.calls[1]["vad_parameters"]["threshold"] == 0.50
    assert model.calls[1]["beam_size"] == 8
    assert "VocabloSintetico" in model.calls[0]["initial_prompt"]
    assert model.calls[0]["hotwords"] == "ayuda, VocabloSintetico"
    assert model.calls[1]["initial_prompt"] is None
    assert model.calls[1]["hotwords"] is None
    assert model.calls[1]["hallucination_silence_threshold"] == 2.0
    assert refined[0].second_pass is True
    assert refined[0].no_speech_probability == 0.1


def test_live_hotword_update_changes_the_next_primary_pass() -> None:
    transcriber = FasterWhisperTranscriber(FasterWhisperConfig(hotwords=["antes"]))
    model = FakeModel()
    transcriber._model = model
    pcm_format = PcmFormat()
    pcm = bytes(pcm_format.bytes_for_seconds(1))

    transcriber.update_hotwords(["después"])
    transcriber.transcribe(pcm, pcm_format, 0)

    assert model.calls[0]["hotwords"] == "después"
    assert "antes" not in model.calls[0]["hotwords"]
