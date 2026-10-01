from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auralwarden.audio import PcmFormat
from auralwarden.models import TranscriptEntry, TranscriptWord


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WhisperCppUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class WhisperCppConfig:
    executable: str
    model: str
    language: str = "es"
    threads: int = 4
    initial_prompt: str = ""
    hotwords: list[str] | None = None
    vocabulary: list[str] | None = None
    use_gpu: bool = True
    timeout_seconds: int = 180


def _timestamp_seconds(value: object, *, milliseconds: bool = False) -> float:
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if milliseconds else float(value)
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return float(text)
    except ValueError:
        return 0.0


def _range_seconds(item: dict[str, Any]) -> tuple[float, float]:
    offsets = item.get("offsets") or {}
    timestamps = item.get("timestamps") or {}
    source = offsets or timestamps
    milliseconds = bool(offsets)
    start = _timestamp_seconds(
        source.get("from", source.get("start", 0)), milliseconds=milliseconds
    )
    end = _timestamp_seconds(
        source.get("to", source.get("end", start)), milliseconds=milliseconds
    )
    return start, max(start, end)


def parse_whisper_cpp_json(
    payload: dict[str, Any], offset_seconds: float, *, high_precision: bool = False
) -> list[TranscriptEntry]:
    rows = payload.get("transcription") or payload.get("segments") or []
    entries: list[TranscriptEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        start, end = _range_seconds(row)
        tokens = row.get("tokens") or []
        words: list[TranscriptWord] = []
        probabilities: list[float] = []
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_text = str(token.get("text") or token.get("token") or "")
            token_start, token_end = _range_seconds(token)
            probability = token.get("p", token.get("probability"))
            normalized_probability = None
            if probability is not None:
                try:
                    normalized_probability = max(0.0, min(1.0, float(probability)))
                    probabilities.append(normalized_probability)
                except (TypeError, ValueError):
                    normalized_probability = None
            if token_text.strip() and token_end >= token_start:
                words.append(
                    TranscriptWord(
                        text=token_text,
                        start_seconds=offset_seconds + token_start,
                        end_seconds=offset_seconds + token_end,
                        probability=normalized_probability,
                    )
                )
        confidence = sum(probabilities) / len(probabilities) if probabilities else None
        entries.append(
            TranscriptEntry(
                elapsed_seconds=offset_seconds + start,
                end_seconds=offset_seconds + end,
                speaker_id="Speaker 1",
                text=text,
                confidence=confidence,
                source="whisper.cpp",
                second_pass=high_precision,
                words=words,
            )
        )
    return entries


class WhisperCppTranscriber:
    def __init__(self, config: WhisperCppConfig) -> None:
        self.config = config
        self._resource_profile = "normal"

    def set_resource_profile(self, profile: str) -> None:
        self._resource_profile = profile

    def update_hotwords(self, hotwords: list[str]) -> None:
        self.config.hotwords = list(hotwords)

    def transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool = False,
    ) -> list[TranscriptEntry]:
        return self._transcribe(
            pcm,
            pcm_format,
            offset_seconds,
            high_precision=high_precision,
            use_guidance=True,
        )

    def transcribe_verification(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
    ) -> list[TranscriptEntry]:
        return self._transcribe(
            pcm,
            pcm_format,
            offset_seconds,
            high_precision=True,
            use_guidance=False,
        )

    def _transcribe(
        self,
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
        *,
        high_precision: bool,
        use_guidance: bool,
    ) -> list[TranscriptEntry]:
        executable = Path(self.config.executable).expanduser()
        model = Path(self.config.model).expanduser()
        if not executable.is_file() or not model.is_file():
            raise WhisperCppUnavailable(
                "El componente whisper.cpp o su modelo GGML/GGUF no están disponibles."
            )
        if pcm_format.channels != 1 or pcm_format.sample_width != 2:
            raise ValueError("whisper.cpp requiere PCM mono de 16 bits.")
        threads = max(1, self.config.threads)
        if self._resource_profile == "constrained":
            threads = min(threads, 2)
        elif self._resource_profile == "critical":
            threads = 1
        with tempfile.TemporaryDirectory(prefix="auralwarden-stt-") as temporary:
            root = Path(temporary)
            wav_path = root / "window.wav"
            output_prefix = root / "result"
            with wave.open(str(wav_path), "wb") as writer:
                writer.setnchannels(pcm_format.channels)
                writer.setsampwidth(pcm_format.sample_width)
                writer.setframerate(pcm_format.sample_rate)
                writer.writeframes(pcm)
            command = [
                str(executable),
                "-m", str(model),
                "-f", str(wav_path),
                "-l", self.config.language,
                "-t", str(threads),
                "-ojf",
                "-of", str(output_prefix),
                "-np",
            ]
            prompt_parts = [self.config.initial_prompt.strip()]
            guided_terms = [
                term.strip()
                for term in [
                    *(self.config.hotwords or []),
                    *(self.config.vocabulary or []),
                ]
                if term.strip()
            ]
            if guided_terms:
                prompt_parts.append("Vocabulario probable: " + ", ".join(guided_terms))
            prompt = ". ".join(part for part in prompt_parts if part)
            if use_guidance and prompt:
                command.extend(["--prompt", prompt])
            if not self.config.use_gpu:
                command.append("-ng")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
            json_path = output_prefix.with_suffix(".json")
            if result.returncode != 0 or not json_path.is_file():
                detail = (result.stderr or result.stdout).strip()[-600:]
                raise WhisperCppUnavailable(
                    f"whisper.cpp no pudo transcribir el audio: {detail or 'sin detalles'}"
                )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            return parse_whisper_cpp_json(
                payload, offset_seconds, high_precision=high_precision
            )
