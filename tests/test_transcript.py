from pathlib import Path

from auralwarden.models import TranscriptEntry
from auralwarden.transcript import TranscriptBuffer, group_transcript_entries


def test_transcript_export_and_speaker_rename(tmp_path: Path) -> None:
    transcript = TranscriptBuffer()
    transcript.add(TranscriptEntry(65, "Speaker 1", "Texto de prueba", hotwords=["prueba"]))
    transcript.rename_speaker("Speaker 1", "Ana")
    output = tmp_path / "session.txt"
    transcript.export_text(output)
    content = output.read_text(encoding="utf-8")
    assert "[00:01:05] Ana: Texto de prueba" in content
    assert transcript.dirty is False


def test_consecutive_fragments_are_exported_as_readable_paragraphs(
    tmp_path: Path,
) -> None:
    transcript = TranscriptBuffer()
    transcript.add(TranscriptEntry(180, "Speaker 1", "Primera parte", end_seconds=184))
    transcript.add(
        TranscriptEntry(184, "Speaker 1", "que continúa la idea.", end_seconds=188)
    )
    transcript.add(TranscriptEntry(189, "Speaker 2", "Respuesta breve.", end_seconds=192))
    transcript.add(TranscriptEntry(205, "Speaker 2", "Después de una pausa."))

    paragraphs = group_transcript_entries(transcript.entries)
    assert [paragraph.text for paragraph in paragraphs] == [
        "Primera parte que continúa la idea.",
        "Respuesta breve.",
        "Después de una pausa.",
    ]

    output = tmp_path / "paragraphs.txt"
    transcript.export_text(output)
    content = output.read_text(encoding="utf-8")
    assert "[00:03:00] Speaker 1: Primera parte que continúa la idea." in content
    assert "Primera parte\n" not in content


def test_paragraph_uses_earliest_timestamp_when_fragments_arrive_out_of_order() -> None:
    paragraphs = group_transcript_entries(
        [
            TranscriptEntry(181, "Speaker 1", "Fragmento recibido primero", end_seconds=184),
            TranscriptEntry(180, "Speaker 1", "fragmento ligeramente anterior", end_seconds=183),
        ]
    )

    assert len(paragraphs) == 1
    assert paragraphs[0].display_timestamp() == "00:03:00"
