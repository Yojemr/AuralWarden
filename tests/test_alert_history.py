from pathlib import Path

from auralwarden.alert_history import AlertHistoryStore


def test_alert_history_adds_detection_and_attaches_evidence(tmp_path: Path) -> None:
    store = AlertHistoryStore(tmp_path / "alert-history.json")
    session = tmp_path / "session"
    store.add_detection(
        {
            "event_id": "evt-1",
            "phrase": "asistencia",
            "score": 97,
            "elapsed_seconds": 65,
            "context": "Ahora tomaremos asistencia",
            "speaker_id": "Ana",
        },
        source_title="Reunión",
        session_path=session,
    )
    store.attach_clip("evt-1", str(tmp_path / "clip.mp4"), "video/mp4")

    records = store.records()
    assert len(records) == 1
    assert records[0]["phrase"] == "asistencia"
    assert records[0]["source"] == "Reunión"
    assert records[0]["session_path"] == str(session)
    assert records[0]["video_clip"].endswith("clip.mp4")


def test_alert_history_updates_existing_event_without_duplicates(tmp_path: Path) -> None:
    store = AlertHistoryStore(tmp_path / "alert-history.json")
    payload = {"event_id": "evt-1", "phrase": "ayuda", "score": 90}
    store.add_detection(payload)
    store.attach_clip("evt-1", str(tmp_path / "clip.wav"), "audio/wav")
    store.add_detection({**payload, "score": 99})

    records = store.records()
    assert len(records) == 1
    assert records[0]["score"] == 99
    assert records[0]["audio_clip"].endswith("clip.wav")
