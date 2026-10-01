import json
from pathlib import Path

from auralwarden.migration import migrate_latest_portable_installation


def test_portable_migration_links_models_and_ignores_personal_outputs(tmp_path: Path) -> None:
    old_root = tmp_path / "AuralWarden-0.4.1"
    new_root = tmp_path / "AuralWarden-0.5.0"
    old_data = old_root / "data"
    model = old_data / "models" / "large-v3-turbo" / "model.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model-data")
    (old_data / "sessions" / "private").mkdir(parents=True)
    (old_data / "sessions" / "private" / "transcript.txt").write_text("private")
    (old_data / "settings.json").write_text(
        json.dumps({"schema_version": 8, "model_name": str(model.parent), "hotwords": []}),
        encoding="utf-8",
    )
    (old_data / "speaker-profiles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "name": "Ana",
                        "embedding": [1.0, 0.0],
                        "created_at": "2026-08-28T18:00:00",
                        "updated_at": "2026-08-28T18:00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (old_data / "presets.json").write_text(
        json.dumps({"schema_version": 1, "presets": [{"name": "Trabajo", "values": {}}]}),
        encoding="utf-8",
    )
    (old_data / "alert-history.json").write_text(
        json.dumps({"schema_version": 1, "alerts": [{"event_id": "evt-1"}]}),
        encoding="utf-8",
    )
    new_root.mkdir()

    result = migrate_latest_portable_installation(new_root, new_root / "data")

    assert result is not None and result.settings_imported
    assert result.speaker_profiles_imported
    assert result.presets_imported
    assert result.alert_history_imported
    linked = new_root / "data" / "models" / "large-v3-turbo" / "model.bin"
    assert linked.read_bytes() == b"model-data"
    assert linked.stat().st_ino == model.stat().st_ino
    assert not (new_root / "data" / "sessions").exists()
    assert (new_root / "data" / "speaker-profiles.json").is_file()
    assert (new_root / "data" / "presets.json").is_file()
    assert (new_root / "data" / "alert-history.json").is_file()
    migrated = json.loads((new_root / "data" / "settings.json").read_text(encoding="utf-8"))
    assert Path(migrated["model_name"]) == linked.parent.resolve()
