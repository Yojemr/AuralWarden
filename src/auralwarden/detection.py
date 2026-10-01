from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from auralwarden.hotwords import normalize_text
from auralwarden.models import DetectionEvent, HotwordMatch, TranscriptEntry


@dataclass(frozen=True, slots=True)
class FusionResult:
    event: DetectionEvent
    created: bool


class DetectionFusion:
    """Merges repeated detections of the same phrase within a time window."""

    def __init__(self, merge_seconds: float = 20.0) -> None:
        self.merge_seconds = max(0.0, merge_seconds)
        self._latest_by_phrase: dict[str, DetectionEvent] = {}

    def add(self, match: HotwordMatch, entry: TranscriptEntry) -> FusionResult:
        key = normalize_text(match.phrase)
        elapsed = self._match_elapsed(match, entry)
        existing = self._latest_by_phrase.get(key)
        if existing is not None and abs(elapsed - existing.elapsed_seconds) <= self.merge_seconds:
            existing.elapsed_seconds = max(existing.elapsed_seconds, elapsed)
            existing.last_detected_at = datetime.now()
            existing.occurrences += 1
            if match.score >= existing.score:
                existing.score = match.score
                existing.context = entry.text
                existing.matched_text = match.matched_text
                existing.second_pass = entry.second_pass
            return FusionResult(existing, created=False)

        event = DetectionEvent(
            phrase=match.phrase,
            score=match.score,
            elapsed_seconds=elapsed,
            context=entry.text,
            matched_text=match.matched_text,
            speaker_id=entry.speaker_id,
            second_pass=entry.second_pass,
        )
        self._latest_by_phrase[key] = event
        return FusionResult(event, created=True)

    @staticmethod
    def _match_elapsed(match: HotwordMatch, entry: TranscriptEntry) -> float:
        target = normalize_text(match.matched_text or match.phrase)
        target_tokens = target.split()
        word_tokens: list[tuple[str, float]] = []
        for word in entry.words:
            normalized = normalize_text(word.text)
            for token in normalized.split():
                word_tokens.append((token, word.end_seconds))
        if target_tokens and word_tokens:
            size = len(target_tokens)
            for index in range(0, len(word_tokens) - size + 1):
                candidate = [item[0] for item in word_tokens[index : index + size]]
                if candidate == target_tokens:
                    return word_tokens[index + size - 1][1]
        return entry.end_seconds or entry.elapsed_seconds

    def clear(self) -> None:
        self._latest_by_phrase.clear()
