from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auralwarden.models import AppSettings


VERSION_PATTERN = re.compile(r"^AuralWarden-(\d+(?:\.\d+){1,3})$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source_root: Path
    settings_imported: bool
    speaker_profiles_imported: bool
    linked_files: int
    skipped_files: int
    presets_imported: bool = False
    alert_history_imported: bool = False


def find_previous_portable_installations(current_root: Path) -> list[Path]:
    parent = current_root.resolve().parent
    candidates: list[tuple[tuple[int, ...], Path]] = []
    try:
        children = tuple(parent.iterdir())
    except OSError:
        return []
    for child in children:
        match = VERSION_PATTERN.match(child.name)
        if child.resolve() == current_root.resolve() or match is None:
            continue
        if not (child / "data" / "settings.json").is_file():
            continue
        version = tuple(int(part) for part in match.group(1).split("."))
        candidates.append((version, child))
    return [path for _, path in sorted(candidates, reverse=True)]


def migrate_latest_portable_installation(
    current_root: Path,
    destination_data: Path,
) -> MigrationResult | None:
    if (destination_data / "settings.json").exists():
        return None
    candidates = find_previous_portable_installations(current_root)
    if not candidates:
        return None
    source_root = candidates[0]
    source_data = source_root / "data"
    destination_data.mkdir(parents=True, exist_ok=True)
    settings_imported = _migrate_settings(source_data, destination_data)
    speaker_profiles_imported = _migrate_speaker_profiles(
        source_data, destination_data
    )
    presets_imported = _migrate_local_json(
        source_data, destination_data, "presets.json", "presets"
    )
    alert_history_imported = _migrate_local_json(
        source_data, destination_data, "alert-history.json", "alerts"
    )
    linked = skipped = 0
    for relative in (Path("models"), Path("runtime") / "components"):
        copied, ignored = _link_tree(source_data / relative, destination_data / relative)
        linked += copied
        skipped += ignored
    if settings_imported:
        _rewrite_internal_paths(
            destination_data / "settings.json", source_data, destination_data
        )
    report = {
        "source": str(source_root),
        "settings_imported": settings_imported,
        "speaker_profiles_imported": speaker_profiles_imported,
        "presets_imported": presets_imported,
        "alert_history_imported": alert_history_imported,
        "linked_files": linked,
        "skipped_files": skipped,
    }
    (destination_data / "migration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return MigrationResult(
        source_root,
        settings_imported,
        speaker_profiles_imported,
        linked,
        skipped,
        presets_imported,
        alert_history_imported,
    )


def _migrate_settings(source_data: Path, destination_data: Path) -> bool:
    try:
        raw = json.loads((source_data / "settings.json").read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        settings = AppSettings.from_dict(raw)
        (destination_data / "settings.json").write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def _migrate_speaker_profiles(source_data: Path, destination_data: Path) -> bool:
    source = source_data / "speaker-profiles.json"
    destination = destination_data / "speaker-profiles.json"
    if not source.is_file() or destination.exists():
        return False
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("profiles"), list):
            return False
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)
        return True
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def _migrate_local_json(
    source_data: Path,
    destination_data: Path,
    filename: str,
    list_key: str,
) -> bool:
    source = source_data / filename
    destination = destination_data / filename
    if not source.is_file() or destination.exists():
        return False
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get(list_key), list):
            return False
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)
        return True
    except (OSError, UnicodeError, ValueError, TypeError):
        return False
def _link_tree(source: Path, destination: Path) -> tuple[int, int]:
    if not source.is_dir():
        return 0, 0
    linked = skipped = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file() or target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(item, target)
            linked += 1
        except OSError:
            skipped += 1
    return linked, skipped


def _rewrite_internal_paths(path: Path, source_data: Path, destination_data: Path) -> None:
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return
    for key in (
        "model_name",
        "diarization_segmentation_model",
        "diarization_embedding_model",
        "whisper_cpp_executable",
        "whisper_cpp_model",
    ):
        value = str(raw.get(key) or "")
        try:
            relative = Path(value).resolve().relative_to(source_data.resolve())
        except (OSError, ValueError):
            continue
        candidate = destination_data / relative
        if candidate.exists():
            raw[key] = str(candidate.resolve())
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
