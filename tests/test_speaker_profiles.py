from __future__ import annotations

import json

import pytest

from auralwarden.speaker_profiles import SpeakerProfileStore


def test_voice_profiles_are_normalized_updated_and_deleted(tmp_path) -> None:
    path = tmp_path / "speaker-profiles.json"
    store = SpeakerProfileStore(path)

    created = store.save_embedding("Ana", [3.0, 4.0])
    assert created.name == "Ana"
    assert created.embedding == pytest.approx([0.6, 0.8])
    assert store.names() == ["Ana"]

    updated = store.save_embedding("ana", [0.0, 2.0])
    assert updated.name == "ana"
    assert store.embeddings()["ana"] == pytest.approx([0.0, 1.0])
    assert len(store.load()) == 1

    assert store.delete(["ANA"]) == 1
    assert store.load() == []
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_invalid_voice_embedding_is_rejected(tmp_path) -> None:
    store = SpeakerProfileStore(tmp_path / "speaker-profiles.json")
    with pytest.raises(ValueError, match="huella"):
        store.save_embedding("Ana", [0.0, 0.0])
