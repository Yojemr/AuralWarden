from pathlib import Path

from auralwarden.models import TranscriptEntry
from auralwarden.session import SessionWorkspace
from auralwarden.session_recovery import discard_recovery, find_recoverable_transcripts


def test_interrupted_session_transcript_can_be_recovered(tmp_path: Path) -> None:
    session = SessionWorkspace(tmp_path, "https://youtube.com/watch?v=test", "Clase")
    session.update_metadata(status="running")
    session.append_transcript_entry(
        TranscriptEntry(12.5, "Speaker 1", "Texto recuperable", end_seconds=14)
    )

    recoveries = find_recoverable_transcripts(tmp_path)

    assert len(recoveries) == 1
    assert recoveries[0].entries[0].text == "Texto recuperable"
    discard_recovery(recoveries[0])
    assert find_recoverable_transcripts(tmp_path) == []


def test_clean_session_is_not_offered_for_recovery(tmp_path: Path) -> None:
    session = SessionWorkspace(tmp_path, "demo://test")
    session.append_transcript_entry(TranscriptEntry(0, "Speaker 1", "Texto"))
    session.update_metadata(status="stopped")

    assert find_recoverable_transcripts(tmp_path) == []
