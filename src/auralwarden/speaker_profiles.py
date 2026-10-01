from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from auralwarden.paths import speaker_profiles_path


@dataclass(slots=True)
class VoiceProfile:
    name: str
    embedding: list[float]
    created_at: str
    updated_at: str


class SpeakerProfileStore:
    """Stores voluntary voice embeddings locally without retaining audio."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or speaker_profiles_path()

    def load(self) -> list[VoiceProfile]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        profiles = raw.get("profiles", []) if isinstance(raw, dict) else []
        result: list[VoiceProfile] = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            embedding = self._clean_embedding(item.get("embedding", []))
            if not name or not embedding:
                continue
            created = str(item.get("created_at") or datetime.now().isoformat())
            updated = str(item.get("updated_at") or created)
            result.append(VoiceProfile(name, embedding, created, updated))
        return result

    def embeddings(self) -> dict[str, list[float]]:
        return {profile.name: profile.embedding for profile in self.load()}

    def names(self) -> list[str]:
        return [profile.name for profile in self.load()]

    def save_embedding(self, name: str, embedding: Iterable[float]) -> VoiceProfile:
        clean_name = " ".join(name.split()).strip()
        clean_embedding = self._clean_embedding(embedding)
        if not clean_name:
            raise ValueError("Escribe un nombre para el perfil de voz.")
        if not clean_embedding:
            raise ValueError("La muestra no produjo una huella de voz válida.")
        now = datetime.now().isoformat()
        profiles = self.load()
        existing = next(
            (item for item in profiles if item.name.casefold() == clean_name.casefold()),
            None,
        )
        if existing is None:
            profile = VoiceProfile(clean_name, clean_embedding, now, now)
            profiles.append(profile)
        else:
            existing.name = clean_name
            existing.embedding = clean_embedding
            existing.updated_at = now
            profile = existing
        self._write(profiles)
        return profile

    def delete(self, names: Iterable[str]) -> int:
        targets = {str(name).strip().casefold() for name in names if str(name).strip()}
        profiles = self.load()
        kept = [item for item in profiles if item.name.casefold() not in targets]
        removed = len(profiles) - len(kept)
        if removed:
            self._write(kept)
        return removed

    def _write(self, profiles: list[VoiceProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "profiles": [asdict(profile) for profile in profiles],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    @staticmethod
    def _clean_embedding(values: Iterable[float]) -> list[float]:
        try:
            result = [float(value) for value in values]
        except (TypeError, ValueError):
            return []
        if not result or len(result) > 4096 or not all(math.isfinite(value) for value in result):
            return []
        norm = math.sqrt(sum(value * value for value in result))
        if norm <= 0:
            return []
        return [value / norm for value in result]
