from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from auralwarden.audio import PcmFormat
from auralwarden.diarization.base import SpeakerTurn
from auralwarden.models import TranscriptEntry, TranscriptWord


class SherpaOnnxUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class SherpaDiarizerConfig:
    segmentation_model: str
    embedding_model: str
    num_speakers: int = 0
    cluster_threshold: float = 0.75
    speaker_match_threshold: float = 0.32
    voice_profile_threshold: float = 0.55
    voice_profiles: dict[str, list[float]] | None = None
    num_threads: int = 2
    provider: str = "cpu"
    window_shift_ratio: float = 0.2
    min_duration_on: float = 0.4
    min_duration_off: float = 0.5
    minimum_embedding_seconds: float = 0.5
    recent_turn_seconds: float = 30.0
    speaker_continuity_seconds: float = 3.0
    candidate_retention_seconds: float = 40.0
    candidate_confirmation_hits: int = 3
    candidate_confirmation_seconds: float = 3.0


@dataclass(slots=True, eq=False)
class _SpeakerCandidate:
    embedding: Any
    weight: float
    hits: int
    last_window_offset: float


class SherpaOnnxDiarizer:
    """Windowed local diarization with persistent speaker embeddings."""

    def __init__(self, config: SherpaDiarizerConfig) -> None:
        self.config = config
        self._diarizer: Any = None
        self._extractor: Any = None
        self._np: Any = None
        self._centroids: dict[str, Any] = {}
        self._centroid_weights: dict[str, float] = {}
        self._profile_centroids: dict[str, Any] = {}
        self._recent_turns: list[SpeakerTurn] = []
        self._speaker_candidates: list[_SpeakerCandidate] = []
        self._next_speaker = 1

    def _load(self) -> None:
        if self._diarizer is not None:
            return
        segmentation = Path(self.config.segmentation_model).expanduser().resolve()
        embedding = Path(self.config.embedding_model).expanduser().resolve()
        if not segmentation.is_file() or not embedding.is_file():
            raise SherpaOnnxUnavailable(
                "Faltan los modelos locales de diarización. "
                "Ejecute 'download-diarization-models'."
            )
        try:
            import numpy as np
            import sherpa_onnx
        except ImportError as exc:
            raise SherpaOnnxUnavailable(
                "sherpa-onnx no está instalado. Instale el extra 'diarization'."
            ) from exc

        embedding_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=max(1, self.config.num_threads),
            provider=self.config.provider,
        )
        diarization_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(segmentation),
                    window_shift_ratio=self.config.window_shift_ratio,
                )
            ),
            embedding=embedding_config,
            clustering=sherpa_onnx.FastClusteringConfig(
                # A known participant count applies to the complete session,
                # not to every short transcription window.
                num_clusters=-1,
                threshold=self.config.cluster_threshold,
            ),
            min_duration_on=self.config.min_duration_on,
            min_duration_off=self.config.min_duration_off,
        )
        if not diarization_config.validate() or not embedding_config.validate():
            raise SherpaOnnxUnavailable("La configuración de diarización no es válida.")
        self._diarizer = sherpa_onnx.OfflineSpeakerDiarization(diarization_config)
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(embedding_config)
        self._np = np
        self._load_voice_profiles()

    def _load_voice_profiles(self) -> None:
        np = self._np
        self._profile_centroids.clear()
        for name, values in (self.config.voice_profiles or {}).items():
            clean_name = " ".join(str(name).split()).strip()
            if not clean_name:
                continue
            try:
                embedding = np.asarray(values, dtype=np.float32)
            except (TypeError, ValueError):
                continue
            if embedding.ndim != 1 or not len(embedding):
                continue
            norm = float(np.linalg.norm(embedding))
            if norm > 0:
                self._profile_centroids[clean_name] = embedding / norm

    def assign(
        self,
        entries: list[TranscriptEntry],
        pcm: bytes,
        pcm_format: PcmFormat,
        offset_seconds: float,
    ) -> list[TranscriptEntry]:
        if not entries or not pcm:
            return entries
        if pcm_format.sample_rate != 16_000 or pcm_format.channels != 1:
            raise ValueError("La diarización requiere audio mono de 16 kHz.")
        if pcm_format.sample_width != 2:
            raise ValueError("La diarización requiere PCM de 16 bits.")
        self._load()
        np = self._np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        raw_turns = self._diarizer.process(audio).sort_by_start_time()
        local_turns = [
            (
                int(turn.speaker),
                max(0.0, float(turn.start)),
                min(len(audio) / pcm_format.sample_rate, float(turn.end)),
            )
            for turn in raw_turns
            if float(turn.end) > float(turn.start)
        ]
        if not local_turns:
            return entries
        mapping, confidences = self._map_local_speakers(
            local_turns,
            audio,
            pcm_format.sample_rate,
            offset_seconds,
        )
        turns = [
            SpeakerTurn(
                offset_seconds + start,
                offset_seconds + end,
                mapping[local_id],
                confidences.get(local_id),
            )
            for local_id, start, end in local_turns
        ]
        self._remember_turns(turns)
        assigned: list[TranscriptEntry] = []
        for entry in entries:
            assigned.extend(self._assign_entry(entry, turns))
        return assigned or entries

    def _map_local_speakers(
        self,
        local_turns: list[tuple[int, float, float]],
        audio: Any,
        sample_rate: int,
        offset_seconds: float,
    ) -> tuple[dict[int, str], dict[int, float]]:
        mapping: dict[int, str] = {}
        confidences: dict[int, float] = {}
        # Number new speakers in the order in which they first become audible.
        # The diarization model's local cluster identifiers are arbitrary and
        # otherwise a session could begin with a confusing "Speaker 2".
        local_ids = sorted(
            {item[0] for item in local_turns},
            key=lambda local_id: min(
                item[1] for item in local_turns if item[0] == local_id
            ),
        )
        for local_id in local_ids:
            relative = [item for item in local_turns if item[0] == local_id]
            duration = self._turn_duration(relative)
            overlap_speaker, overlap_score = self._speaker_from_overlap(
                relative, offset_seconds
            )
            continuity_speaker = self._speaker_from_continuity(
                relative, offset_seconds
            )
            embedding = self._embedding_for_turns(relative, audio, sample_rate)
            profile_speaker, profile_similarity = self._best_profile_match(embedding)
            best_speaker, similarity = self._best_centroid_match(embedding)
            matched_speaker = (
                best_speaker
                if best_speaker is not None
                and similarity >= self.config.speaker_match_threshold
                else None
            )
            update_centroid = False

            overlap_is_supported = (
                overlap_speaker is not None
                and overlap_score >= 0.25
                and (
                    embedding is None
                    or (
                        best_speaker == overlap_speaker
                        and similarity >= self.config.speaker_match_threshold
                    )
                )
            )
            if (
                profile_speaker is not None
                and profile_similarity >= self.config.voice_profile_threshold
            ):
                speaker = profile_speaker
                confidence = profile_similarity
                profile_centroid = self._profile_centroids[profile_speaker]
                self._centroids.setdefault(profile_speaker, profile_centroid.copy())
                self._centroid_weights.setdefault(profile_speaker, 30.0)
            elif overlap_is_supported:
                speaker = overlap_speaker
                confidence = max(
                    overlap_score,
                    similarity if best_speaker == speaker else 0.0,
                )
                update_centroid = embedding is not None
            elif matched_speaker is not None:
                speaker = matched_speaker
                confidence = similarity
                update_centroid = True
            elif not self._centroids:
                speaker = self._new_speaker()
                confidence = None
                update_centroid = embedding is not None
            elif self._speaker_limit_reached():
                speaker = best_speaker or continuity_speaker or self._latest_speaker()
                confidence = similarity if best_speaker is not None else 0.0
            elif embedding is None:
                speaker = continuity_speaker or self._latest_speaker()
                confidence = 0.0
            else:
                confirmed_embedding = self._confirm_speaker_candidate(
                    embedding, duration, offset_seconds
                )
                confirmed_speaker, confirmed_similarity = self._best_centroid_match(
                    confirmed_embedding
                )
                if (
                    confirmed_embedding is not None
                    and confirmed_speaker is not None
                    and confirmed_similarity >= self.config.speaker_match_threshold
                ):
                    # The averaged candidate may match an established voice even
                    # when one noisy window did not. Reuse that identity instead
                    # of creating a duplicate label.
                    speaker = confirmed_speaker
                    confidence = confirmed_similarity
                    embedding = confirmed_embedding
                    update_centroid = True
                elif confirmed_embedding is not None:
                    speaker = self._new_speaker()
                    confidence = None
                    embedding = confirmed_embedding
                    update_centroid = True
                else:
                    # One uncertain observation is not enough evidence for a new
                    # identity. Keep the most plausible label until it repeats.
                    speaker = continuity_speaker or best_speaker or self._latest_speaker()
                    confidence = similarity if best_speaker == speaker else 0.0

            if speaker in self._profile_centroids and not (
                speaker == profile_speaker
                and profile_similarity >= self.config.voice_profile_threshold
            ):
                generic = [name for name in self._centroids if name not in self._profile_centroids]
                speaker = max(generic, key=lambda name: self._centroid_weights.get(name, 0.0)) if generic else None
                confidence = 0.0
                update_centroid = False
            if speaker is None:
                speaker = self._new_speaker()
                update_centroid = embedding is not None
            mapping[local_id] = speaker
            confidences[local_id] = confidence if confidence is not None else 0.0
            if embedding is not None and update_centroid:
                self._update_centroid(speaker, embedding, duration)
        return mapping, confidences

    def _best_centroid_match(self, embedding: Any | None) -> tuple[str | None, float]:
        if embedding is None or not self._centroids:
            return None, 0.0
        return max(
            (
                (speaker, float(embedding @ centroid))
                for speaker, centroid in self._centroids.items()
            ),
            key=lambda item: item[1],
        )

    def _best_profile_match(self, embedding: Any | None) -> tuple[str | None, float]:
        if embedding is None or not self._profile_centroids:
            return None, 0.0
        compatible = [
            (speaker, float(embedding @ centroid))
            for speaker, centroid in self._profile_centroids.items()
            if getattr(centroid, "shape", None) == getattr(embedding, "shape", None)
        ]
        if not compatible:
            return None, 0.0
        return max(
            compatible,
            key=lambda item: item[1],
        )

    def export_speaker_embedding(self, speaker: str) -> list[float] | None:
        """Return a normalized session centroid for explicit local enrollment."""
        embedding = self._centroids.get(speaker)
        if embedding is None:
            embedding = self._profile_centroids.get(speaker)
        if embedding is None:
            return None
        return [float(value) for value in embedding.tolist()]

    def _speaker_limit_reached(self) -> bool:
        return (
            self.config.num_speakers > 0
            and len(self._centroids) >= self.config.num_speakers
        )

    def _new_speaker(self) -> str:
        speaker = f"Speaker {self._next_speaker}"
        self._next_speaker += 1
        return speaker

    def _confirm_speaker_candidate(
        self,
        embedding: Any,
        duration: float,
        window_offset: float,
    ) -> Any | None:
        np = self._np
        cutoff = window_offset - self.config.candidate_retention_seconds
        self._speaker_candidates = [
            candidate
            for candidate in self._speaker_candidates
            if candidate.last_window_offset >= cutoff
        ]
        candidate_threshold = max(
            0.20, self.config.speaker_match_threshold - 0.08
        )
        candidate = None
        similarity = 0.0
        if self._speaker_candidates:
            candidate, similarity = max(
                (
                    (item, float(embedding @ item.embedding))
                    for item in self._speaker_candidates
                ),
                key=lambda item: item[1],
            )
            if similarity < candidate_threshold:
                candidate = None

        weight = max(self.config.minimum_embedding_seconds, duration)
        if candidate is None:
            self._speaker_candidates.append(
                _SpeakerCandidate(embedding, weight, 1, window_offset)
            )
            return None

        combined = (
            candidate.embedding * candidate.weight + embedding * weight
        ) / (candidate.weight + weight)
        norm = float(np.linalg.norm(combined))
        if norm > 0:
            combined /= norm
        candidate.embedding = combined
        candidate.weight += weight
        if candidate.last_window_offset != window_offset:
            candidate.hits += 1
        candidate.last_window_offset = window_offset
        if candidate.hits < max(2, self.config.candidate_confirmation_hits):
            return None
        if candidate.weight < max(
            self.config.minimum_embedding_seconds,
            self.config.candidate_confirmation_seconds,
        ):
            return None
        # NumPy arrays do not have a scalar equality value. Removing a
        # dataclass instance through list.remove() can therefore compare its
        # embedding with an earlier candidate and raise the ambiguous truth
        # value exception. Candidates are session objects, so identity is the
        # correct removal criterion.
        self._speaker_candidates = [
            item for item in self._speaker_candidates if item is not candidate
        ]
        confirmed = candidate.embedding.copy()
        # Remove provisional duplicates that accumulated from overlapping noisy
        # windows. They would otherwise be able to create another label later.
        self._speaker_candidates = [
            item
            for item in self._speaker_candidates
            if float(confirmed @ item.embedding) < candidate_threshold
        ]
        return confirmed

    def _embedding_for_turns(
        self,
        turns: list[tuple[int, float, float]],
        audio: Any,
        sample_rate: int,
    ) -> Any | None:
        np = self._np
        pieces = [
            audio[max(0, int(start * sample_rate)) : min(len(audio), int(end * sample_rate))]
            for _, start, end in turns
            if end > start
        ]
        pieces = [piece for piece in pieces if len(piece)]
        if not pieces:
            return None
        samples = np.concatenate(pieces)
        if len(samples) < int(self.config.minimum_embedding_seconds * sample_rate):
            return None
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=samples)
        stream.input_finished()
        embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(embedding))
        return embedding / norm if norm > 0 else None

    def _speaker_from_overlap(
        self,
        turns: list[tuple[int, float, float]],
        offset_seconds: float,
    ) -> tuple[str | None, float]:
        scores: dict[str, float] = {}
        total = self._turn_duration(turns)
        if total <= 0:
            return None, 0.0
        for _, start, end in turns:
            absolute_start = offset_seconds + start
            absolute_end = offset_seconds + end
            for previous in self._recent_turns:
                overlap = max(
                    0.0,
                    min(absolute_end, previous.end_seconds)
                    - max(absolute_start, previous.start_seconds),
                )
                if overlap > 0:
                    scores[previous.speaker_id] = scores.get(previous.speaker_id, 0.0) + overlap
        if not scores:
            return None, 0.0
        speaker, overlap = max(scores.items(), key=lambda item: item[1])
        return speaker, min(1.0, overlap / total)

    def _speaker_from_continuity(
        self,
        turns: list[tuple[int, float, float]],
        offset_seconds: float,
    ) -> str | None:
        if not turns or not self._recent_turns:
            return None
        absolute_start = offset_seconds + min(item[1] for item in turns)
        preceding = [
            turn
            for turn in self._recent_turns
            if turn.end_seconds <= absolute_start
            and absolute_start - turn.end_seconds
            <= self.config.speaker_continuity_seconds
        ]
        if not preceding:
            return None
        return max(preceding, key=lambda turn: turn.end_seconds).speaker_id

    def _latest_speaker(self) -> str | None:
        if self._recent_turns:
            return max(
                self._recent_turns, key=lambda turn: turn.end_seconds
            ).speaker_id
        if self._centroids:
            return max(
                self._centroids,
                key=lambda speaker: self._centroid_weights.get(speaker, 0.0),
            )
        return None

    def _update_centroid(self, speaker: str, embedding: Any, duration: float) -> None:
        if speaker in self._profile_centroids:
            return
        np = self._np
        weight = max(self.config.minimum_embedding_seconds, duration)
        previous = self._centroids.get(speaker)
        if previous is None:
            self._centroids[speaker] = embedding
            self._centroid_weights[speaker] = weight
            return
        old_weight = self._centroid_weights[speaker]
        centroid = (previous * old_weight + embedding * weight) / (old_weight + weight)
        norm = float(np.linalg.norm(centroid))
        if norm > 0:
            centroid /= norm
        self._centroids[speaker] = centroid
        self._centroid_weights[speaker] = old_weight + weight

    def _assign_entry(
        self,
        entry: TranscriptEntry,
        turns: list[SpeakerTurn],
    ) -> list[TranscriptEntry]:
        dominant, dominant_confidence = self._dominant_speaker(
            entry.elapsed_seconds,
            entry.end_seconds or entry.elapsed_seconds,
            turns,
        )
        if not entry.words:
            return [
                replace(
                    entry,
                    speaker_id=dominant or entry.speaker_id,
                    speaker_confidence=dominant_confidence,
                    speaker_profile=self._verified_profile(dominant, dominant_confidence),
                )
            ]

        labels: list[tuple[TranscriptWord, str, float | None]] = []
        for word in entry.words:
            speaker, confidence = self._dominant_speaker(
                word.start_seconds,
                word.end_seconds,
                turns,
            )
            labels.append((word, speaker or dominant or entry.speaker_id, confidence))
        self._smooth_single_word_changes(labels)

        groups: list[list[tuple[TranscriptWord, str, float | None]]] = []
        for item in labels:
            if not groups or groups[-1][-1][1] != item[1]:
                groups.append([item])
            else:
                groups[-1].append(item)
        return [
            replace(
                entry,
                elapsed_seconds=group[0][0].start_seconds,
                end_seconds=group[-1][0].end_seconds,
                speaker_id=group[0][1],
                speaker_confidence=self._mean_confidence(item[2] for item in group),
                speaker_profile=self._verified_profile(
                    group[0][1], min((item[2] or 0.0 for item in group), default=0.0)
                ),
                text="".join(item[0].text for item in group).strip(),
                words=[item[0] for item in group],
            )
            for group in groups
            if any(item[0].text.strip() for item in group)
        ]

    def _verified_profile(self, speaker: str | None, confidence: float | None) -> str:
        return speaker if speaker in self._profile_centroids and (
            confidence is not None and confidence >= self.config.voice_profile_threshold
        ) else ""

    @staticmethod
    def _smooth_single_word_changes(
        labels: list[tuple[TranscriptWord, str, float | None]],
    ) -> None:
        for index in range(1, len(labels) - 1):
            if labels[index - 1][1] != labels[index + 1][1]:
                continue
            if labels[index][1] == labels[index - 1][1]:
                continue
            word, _, _ = labels[index]
            labels[index] = (word, labels[index - 1][1], 0.0)

    @staticmethod
    def _dominant_speaker(
        start: float,
        end: float,
        turns: list[SpeakerTurn],
    ) -> tuple[str | None, float | None]:
        scores: dict[str, float] = {}
        confidences: dict[str, list[float]] = {}
        for turn in turns:
            overlap = max(0.0, min(end, turn.end_seconds) - max(start, turn.start_seconds))
            if overlap <= 0:
                continue
            scores[turn.speaker_id] = scores.get(turn.speaker_id, 0.0) + overlap
            if turn.confidence is not None:
                confidences.setdefault(turn.speaker_id, []).append(turn.confidence)
        if not scores:
            return None, None
        speaker = max(scores.items(), key=lambda item: item[1])[0]
        values = confidences.get(speaker, [])
        return speaker, sum(values) / len(values) if values else None

    def _remember_turns(self, turns: list[SpeakerTurn]) -> None:
        self._recent_turns.extend(turns)
        latest = max((turn.end_seconds for turn in turns), default=0.0)
        cutoff = latest - self.config.recent_turn_seconds
        self._recent_turns = [
            turn for turn in self._recent_turns if turn.end_seconds >= cutoff
        ]

    @staticmethod
    def _turn_duration(turns: list[tuple[int, float, float]]) -> float:
        return sum(max(0.0, end - start) for _, start, end in turns)

    @staticmethod
    def _mean_confidence(values) -> float | None:
        filtered = [value for value in values if value is not None]
        return sum(filtered) / len(filtered) if filtered else None
