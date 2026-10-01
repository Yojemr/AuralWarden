from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from auralwarden.audio import PcmFormat
from auralwarden.cuda import configure_cuda_dll_search_paths
from auralwarden.models import TranscriptEntry, TranscriptWord


class FasterWhisperUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class FasterWhisperConfig:
    model_name: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "es"
    beam_size: int = 5
    high_precision_beam_size: int = 8
    vad_filter: bool = True
    vad_parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "threshold": 0.35,
            "min_speech_duration_ms": 100,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 350,
        }
    )
    high_precision_vad_filter: bool = True
    high_precision_vad_parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "threshold": 0.50,
            "min_speech_duration_ms": 200,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 250,
        }
    )
    hotwords: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)
    initial_prompt: str = ""
    repetition_penalty: float = 1.05
    hallucination_silence_threshold: float = 2.0
    cpu_threads: int = 4
    num_workers: int = 1
    download_root: str | None = None
    local_files_only: bool = False


class FasterWhisperTranscriber:
    """Lazy faster-whisper adapter; importing the project never loads CUDA."""

    def __init__(self, config: FasterWhisperConfig | None = None) -> None:
        self.config = config or FasterWhisperConfig()
        self._model: Any = None
        self._resource_profile = "normal"

    def set_resource_profile(self, profile: str) -> None:
        self._resource_profile = profile

    def update_hotwords(self, hotwords: list[str]) -> None:
        self.config.hotwords = list(hotwords)

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self.config.device == "cuda":
            configure_cuda_dll_search_paths()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise FasterWhisperUnavailable(
                "faster-whisper no está instalado. Instale el extra 'stt'."
            ) from exc
        self._model = WhisperModel(
            self.config.model_name,
            device=self.config.device,
            compute_type=self.config.compute_type,
            cpu_threads=self.config.cpu_threads,
            num_workers=self.config.num_workers,
            download_root=self.config.download_root,
            local_files_only=self.config.local_files_only,
        )
        return self._model

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
        """Reanalyse audio without user text that the model could echo."""
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
        if pcm_format.channels != 1 or pcm_format.sample_width != 2:
            raise ValueError("faster-whisper requiere PCM mono de 16 bits.")
        try:
            import numpy as np
        except ImportError as exc:
            raise FasterWhisperUnavailable("NumPy no está instalado.") from exc

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        beam_size = (
            self.config.high_precision_beam_size
            if high_precision
            else self.config.beam_size
        )
        if not high_precision and self._resource_profile == "constrained":
            beam_size = min(beam_size, 3)
        elif not high_precision and self._resource_profile == "critical":
            beam_size = min(beam_size, 2)
        terms = list(
            dict.fromkeys(
                word.strip()
                for word in [*self.config.hotwords, *self.config.vocabulary]
                if word.strip()
            )
        )
        hotwords = (", ".join(terms) or None) if use_guidance else None
        prompt_parts = [self.config.initial_prompt.strip()] if use_guidance else []
        vocabulary = ", ".join(
            word.strip() for word in self.config.vocabulary if word.strip()
        )
        if vocabulary and use_guidance:
            prompt_parts.append(f"Vocabulario probable: {vocabulary}.")
        initial_prompt = " ".join(part for part in prompt_parts if part) or None
        vad_filter = (
            self.config.high_precision_vad_filter
            if high_precision
            else self.config.vad_filter
        )
        vad_parameters = (
            self.config.high_precision_vad_parameters
            if high_precision
            else self.config.vad_parameters
        )
        segments, _ = self._load_model().transcribe(
            audio,
            language=self.config.language,
            task="transcribe",
            beam_size=beam_size,
            best_of=beam_size,
            patience=1.2 if high_precision else 1.0,
            repetition_penalty=self.config.repetition_penalty,
            temperature=0.0,
            word_timestamps=True,
            vad_filter=vad_filter,
            vad_parameters=vad_parameters,
            hotwords=hotwords,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            hallucination_silence_threshold=(
                self.config.hallucination_silence_threshold
            ),
        )
        entries: list[TranscriptEntry] = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            probability = None
            if segment.avg_logprob is not None:
                probability = max(0.0, min(1.0, 2.718281828 ** segment.avg_logprob))
            words: list[TranscriptWord] = []
            for word in getattr(segment, "words", None) or []:
                start = getattr(word, "start", None)
                end = getattr(word, "end", None)
                if start is None or end is None:
                    continue
                word_probability = getattr(word, "probability", None)
                words.append(
                    TranscriptWord(
                        text=str(getattr(word, "word", "")),
                        start_seconds=offset_seconds + float(start),
                        end_seconds=offset_seconds + float(end),
                        probability=(
                            max(0.0, min(1.0, float(word_probability)))
                            if word_probability is not None
                            else None
                        ),
                    )
                )
            entries.append(
                TranscriptEntry(
                    elapsed_seconds=offset_seconds + float(segment.start),
                    end_seconds=offset_seconds + float(segment.end),
                    speaker_id="Speaker 1",
                    text=text,
                    confidence=probability,
                    source="faster-whisper",
                    second_pass=high_precision,
                    words=words,
                    no_speech_probability=(
                        max(
                            0.0,
                            min(1.0, float(segment.no_speech_prob)),
                        )
                        if getattr(segment, "no_speech_prob", None) is not None
                        else None
                    ),
                )
            )
        return entries
