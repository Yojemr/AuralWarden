from auralwarden.detection import DetectionFusion
from auralwarden.models import HotwordMatch, TranscriptEntry, TranscriptWord


def test_temporal_fusion_merges_same_phrase() -> None:
    fusion = DetectionFusion(20)
    match = HotwordMatch("contrato", 92, "contato", threshold=88)
    first = fusion.add(match, TranscriptEntry(10, "Speaker 1", "Primer contrato"))
    second = fusion.add(match, TranscriptEntry(24, "Speaker 2", "Otro contrato"))
    assert first.created is True
    assert second.created is False
    assert second.event.event_id == first.event.event_id
    assert second.event.occurrences == 2


def test_temporal_fusion_creates_new_event_outside_window() -> None:
    fusion = DetectionFusion(10)
    match = HotwordMatch("contrato", 100, "contrato", threshold=88, exact=True)
    first = fusion.add(match, TranscriptEntry(10, "Speaker 1", "Contrato"))
    second = fusion.add(match, TranscriptEntry(30, "Speaker 1", "Contrato"))
    assert first.event.event_id != second.event.event_id


def test_detection_uses_word_timestamp_when_available() -> None:
    fusion = DetectionFusion(10)
    entry = TranscriptEntry(
        5,
        "Speaker 1",
        "Necesito ayuda ahora",
        end_seconds=9,
        words=[
            TranscriptWord(" Necesito", 5.0, 5.5, 0.9),
            TranscriptWord(" ayuda", 5.5, 6.1, 0.95),
            TranscriptWord(" ahora", 6.1, 6.7, 0.9),
        ],
    )
    result = fusion.add(
        HotwordMatch("ayuda", 100, "ayuda", exact=True), entry
    )
    assert result.event.elapsed_seconds == 6.1
