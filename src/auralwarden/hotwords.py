from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from auralwarden.models import Hotword, HotwordMatch

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional fallback
    fuzz = None


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[\w]+", without_marks, flags=re.UNICODE))


class HotwordDetector:
    def __init__(self, hotwords: list[Hotword] | None = None) -> None:
        self.hotwords = hotwords or []

    def update(self, hotwords: list[Hotword]) -> None:
        self.hotwords = hotwords

    @property
    def maximum_phrase_words(self) -> int:
        return max(
            (
                len(normalize_text(hotword.phrase).split())
                for hotword in self.hotwords
                if hotword.enabled
            ),
            default=0,
        )

    @staticmethod
    def _ratio(left: str, right: str) -> float:
        if fuzz is not None:
            return float(fuzz.ratio(left, right))
        return SequenceMatcher(None, left, right).ratio() * 100.0

    def evaluate(self, text: str) -> list[HotwordMatch]:
        normalized = normalize_text(text)
        if not normalized:
            return []
        evaluations: list[HotwordMatch] = []
        for hotword in self.hotwords:
            if not hotword.enabled:
                continue
            phrase = normalize_text(hotword.phrase)
            if not phrase:
                continue
            exact_pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
            if re.search(exact_pattern, normalized):
                evaluations.append(
                    HotwordMatch(
                        hotword.phrase,
                        100.0,
                        hotword.phrase,
                        threshold=hotword.threshold,
                        exact=True,
                    )
                )
                continue
            words = normalized.split()
            phrase_words = phrase.split()
            sizes = range(max(1, len(phrase_words) - 1), len(phrase_words) + 2)
            best_score = 0.0
            best_window = ""
            for size in sizes:
                for index in range(0, max(0, len(words) - size + 1)):
                    window = " ".join(words[index : index + size])
                    score = self._ratio(phrase, window)
                    if score > best_score:
                        best_score = score
                        best_window = window
            evaluations.append(
                HotwordMatch(
                    hotword.phrase,
                    best_score,
                    best_window,
                    threshold=hotword.threshold,
                )
            )
        return evaluations

    def find_matches(self, text: str) -> list[HotwordMatch]:
        return [evaluation for evaluation in self.evaluate(text) if evaluation.accepted]

    def find_boundary_matches(
        self, previous_text: str, current_text: str
    ) -> list[HotwordMatch]:
        """Find phrases whose matched words cross a transcript boundary."""

        previous_words = normalize_text(previous_text).split()
        current_words = normalize_text(current_text).split()
        if not previous_words or not current_words:
            return []

        words = [*previous_words, *current_words]
        boundary = len(previous_words)
        matches: list[HotwordMatch] = []
        for hotword in self.hotwords:
            if not hotword.enabled:
                continue
            phrase = normalize_text(hotword.phrase)
            phrase_words = phrase.split()
            if len(phrase_words) < 2:
                continue

            best_score = 0.0
            best_window = ""
            for size in range(max(2, len(phrase_words) - 1), len(phrase_words) + 2):
                first_start = max(0, boundary - size + 1)
                last_start = min(boundary - 1, len(words) - size)
                for start in range(first_start, last_start + 1):
                    end = start + size
                    if not (start < boundary < end):
                        continue
                    window = " ".join(words[start:end])
                    score = 100.0 if window == phrase else self._ratio(phrase, window)
                    if score > best_score:
                        best_score = score
                        best_window = window

            if best_score >= hotword.threshold:
                matches.append(
                    HotwordMatch(
                        hotword.phrase,
                        best_score,
                        best_window,
                        threshold=hotword.threshold,
                        exact=best_window == phrase,
                    )
                )
        return matches

    def find_candidates(self, text: str, margin: int = 8) -> list[HotwordMatch]:
        margin = max(0, margin)
        return [
            evaluation
            for evaluation in self.evaluate(text)
            if evaluation.score >= evaluation.threshold - margin
        ]
