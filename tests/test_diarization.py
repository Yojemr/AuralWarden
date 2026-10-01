from __future__ import annotations

import numpy as np

from auralwarden.diarization.base import SpeakerTurn
from auralwarden.diarization.sherpa import SherpaDiarizerConfig, SherpaOnnxDiarizer
from auralwarden.models import TranscriptEntry, TranscriptWord


def test_diarizer_splits_transcript_by_word_timestamps() -> None:
    diarizer = SherpaOnnxDiarizer(SherpaDiarizerConfig("missing", "missing"))
    entry = TranscriptEntry(
        0,
        "Speaker 1",
        "Hola a todos gracias",
        end_seconds=2,
        words=[
            TranscriptWord(" Hola", 0.0, 0.5, 0.9),
            TranscriptWord(" a", 0.5, 1.0, 0.9),
            TranscriptWord(" todos", 1.0, 1.5, 0.9),
            TranscriptWord(" gracias", 1.5, 2.0, 0.9),
        ],
    )
    turns = [
        SpeakerTurn(0, 1, "Speaker 1", 0.8),
        SpeakerTurn(1, 2, "Speaker 2", 0.9),
    ]

    assigned = diarizer._assign_entry(entry, turns)

    assert [item.speaker_id for item in assigned] == ["Speaker 1", "Speaker 2"]
    assert [item.text for item in assigned] == ["Hola a", "todos gracias"]
    assert assigned[1].speaker_confidence == 0.9


def _prepared_diarizer(*, expected_speakers: int = 0) -> SherpaOnnxDiarizer:
    diarizer = SherpaOnnxDiarizer(
        SherpaDiarizerConfig(
            "missing",
            "missing",
            num_speakers=expected_speakers,
            speaker_match_threshold=0.32,
        )
    )
    diarizer._np = np
    diarizer._centroids = {
        "Speaker 1": np.asarray([1.0, 0.0], dtype=np.float32)
    }
    diarizer._centroid_weights = {"Speaker 1": 4.0}
    diarizer._next_speaker = 2
    return diarizer


def test_uncertain_voice_requires_repeated_windows_before_new_speaker() -> None:
    diarizer = _prepared_diarizer()
    embeddings = iter(
        [
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
        ]
    )
    diarizer._embedding_for_turns = lambda *_: next(embeddings)
    turns = [(0, 0.0, 1.5)]

    first, _ = diarizer._map_local_speakers(turns, np.zeros(1), 16_000, 10.0)
    diarizer._remember_turns([SpeakerTurn(10.0, 11.5, first[0], 0.0)])
    second, _ = diarizer._map_local_speakers(turns, np.zeros(1), 16_000, 14.0)
    third, _ = diarizer._map_local_speakers(turns, np.zeros(1), 16_000, 18.0)

    assert first == {0: "Speaker 1"}
    assert second == {0: "Speaker 1"}
    assert third == {0: "Speaker 2"}
    assert set(diarizer._centroids) == {"Speaker 1", "Speaker 2"}


def test_overlap_does_not_override_a_contradictory_voice_embedding() -> None:
    diarizer = _prepared_diarizer()
    embeddings = iter(
        [
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
        ]
    )
    diarizer._embedding_for_turns = lambda *_: next(embeddings)
    diarizer._recent_turns = [SpeakerTurn(10.0, 12.0, "Speaker 1", 0.9)]

    first, _ = diarizer._map_local_speakers(
        [(0, 0.0, 2.0)], np.zeros(1), 16_000, 11.0
    )
    diarizer._recent_turns = [SpeakerTurn(11.0, 13.0, first[0], 0.0)]
    second, _ = diarizer._map_local_speakers(
        [(0, 0.0, 2.0)], np.zeros(1), 16_000, 12.0
    )
    diarizer._recent_turns = [SpeakerTurn(12.0, 14.0, second[0], 0.0)]
    third, _ = diarizer._map_local_speakers(
        [(0, 0.0, 2.0)], np.zeros(1), 16_000, 14.0
    )

    assert first == {0: "Speaker 1"}
    assert second == {0: "Speaker 1"}
    assert third == {0: "Speaker 2"}


def test_short_repeated_noise_does_not_confirm_a_new_speaker() -> None:
    diarizer = _prepared_diarizer()
    diarizer._embedding_for_turns = lambda *_: np.asarray(
        [0.0, 1.0], dtype=np.float32
    )

    mappings = [
        diarizer._map_local_speakers(
            [(0, 0.0, 0.5)], np.zeros(1), 16_000, offset
        )[0]
        for offset in (10.0, 14.0, 18.0)
    ]

    assert mappings == [{0: "Speaker 1"}] * 3
    assert set(diarizer._centroids) == {"Speaker 1"}


def test_short_turn_without_embedding_does_not_create_spurious_speaker() -> None:
    diarizer = _prepared_diarizer()
    diarizer._embedding_for_turns = lambda *_: None

    mapping, _ = diarizer._map_local_speakers(
        [(0, 0.0, 0.3)], np.zeros(1), 16_000, 40.0
    )

    assert mapping == {0: "Speaker 1"}
    assert diarizer._next_speaker == 2


def test_expected_speaker_count_is_a_global_limit() -> None:
    diarizer = _prepared_diarizer(expected_speakers=1)
    diarizer._embedding_for_turns = lambda *_: np.asarray(
        [0.0, 1.0], dtype=np.float32
    )

    mapping, _ = diarizer._map_local_speakers(
        [(0, 0.0, 2.0)], np.zeros(1), 16_000, 20.0
    )

    assert mapping == {0: "Speaker 1"}
    assert diarizer._next_speaker == 2


def test_saved_voice_profile_has_priority_when_similarity_is_confident() -> None:
    diarizer = _prepared_diarizer()
    diarizer.config.voice_profile_threshold = 0.55
    diarizer._profile_centroids = {
        "Ana": np.asarray([0.0, 1.0], dtype=np.float32)
    }
    diarizer._embedding_for_turns = lambda *_: np.asarray(
        [0.0, 1.0], dtype=np.float32
    )

    mapping, confidences = diarizer._map_local_speakers(
        [(0, 0.0, 2.0)], np.zeros(1), 16_000, 20.0
    )

    assert mapping == {0: "Ana"}
    assert confidences[0] == 1.0
    assert diarizer.export_speaker_embedding("Ana") == [0.0, 1.0]


def test_confirming_second_candidate_never_compares_numpy_arrays_as_booleans() -> None:
    diarizer = _prepared_diarizer()
    first = np.asarray([0.0, 1.0], dtype=np.float32)
    second = np.asarray([-1.0, 0.0], dtype=np.float32)

    assert diarizer._confirm_speaker_candidate(first, 1.0, 1.0) is None
    assert diarizer._confirm_speaker_candidate(second, 1.0, 2.0) is None
    assert diarizer._confirm_speaker_candidate(second, 1.0, 3.0) is None
    confirmed = diarizer._confirm_speaker_candidate(second, 1.0, 4.0)

    assert confirmed is not None
    assert np.allclose(confirmed, second)
