from __future__ import annotations

import json

from auralwarden.transcript_archive import (
    discover_archived_transcripts,
    load_archived_transcript,
)


def test_discovers_one_preferred_transcript_per_session(tmp_path) -> None:
    session = tmp_path / "2026-08-31_10-00-00 - Clase"
    transcripts = session / "transcripts"
    transcripts.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "title": "Clase de prueba",
                "started_at": "2026-08-31T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    text_path = transcripts / "2026-08-31_10-00-00 - Transcripcion.txt"
    json_path = transcripts / "2026-08-31_10-00-00 - Transcripcion.json"
    text_path.write_text("texto", encoding="utf-8")
    json_path.write_text("[]", encoding="utf-8")

    records = discover_archived_transcripts(tmp_path)

    assert len(records) == 1
    assert records[0].path == json_path
    assert records[0].title == "Clase de prueba"
    assert records[0].display_date == "2026-08-31 10:00"


def test_json_transcript_is_rendered_as_readable_paragraphs(tmp_path) -> None:
    path = tmp_path / "transcript.json"
    path.write_text(
        json.dumps(
            [
                {
                    "elapsed_seconds": 60,
                    "end_seconds": 63,
                    "speaker_id": "Ana",
                    "text": "Primera parte",
                    "hotwords": [],
                },
                {
                    "elapsed_seconds": 63,
                    "end_seconds": 66,
                    "speaker_id": "Ana",
                    "text": "que continúa.",
                    "hotwords": ["continúa"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    text, entries = load_archived_transcript(path)

    assert len(entries) == 2
    assert "[00:01:00] Ana" in text
    assert "Primera parte que continúa." in text
    assert "Hotwords: continúa" in text


def test_plain_text_transcript_is_opened_without_conversion(tmp_path) -> None:
    path = tmp_path / "transcript.txt"
    path.write_text("[00:00:10] Speaker 1: Texto legible", encoding="utf-8")

    text, entries = load_archived_transcript(path)

    assert text == "[00:00:10] Speaker 1: Texto legible"
    assert entries == []
