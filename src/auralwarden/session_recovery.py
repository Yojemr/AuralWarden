from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from auralwarden.models import TranscriptEntry, TranscriptWord


INTERRUPTED_STATUSES = {"starting", "running", "waiting", "reconnecting", "failed"}


@dataclass(frozen=True, slots=True)
class RecoverableTranscript:
    session_path: Path
    source: str
    title: str
    started_at: str
    entries: tuple[TranscriptEntry, ...]

    @property
    def journal_path(self) -> Path:
        return self.session_path / "transcript-recovery.jsonl"


def find_recoverable_transcripts(root: Path) -> list[RecoverableTranscript]:
    if not root.is_dir():
        return []
    recovered: list[RecoverableTranscript] = []
    for session_path in root.iterdir():
        if not session_path.is_dir():
            continue
        metadata_path = session_path / "session.json"
        journal_path = session_path / "transcript-recovery.jsonl"
        if not metadata_path.is_file() or not journal_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if str(metadata.get("status") or "").casefold() not in INTERRUPTED_STATUSES:
            continue
        entries = tuple(_read_entries(journal_path))
        if not entries:
            continue
        recovered.append(
            RecoverableTranscript(
                session_path=session_path,
                source=str(metadata.get("source") or ""),
                title=str(metadata.get("title") or session_path.name),
                started_at=str(metadata.get("started_at") or ""),
                entries=entries,
            )
        )
    return sorted(recovered, key=lambda item: item.started_at, reverse=True)


def discard_recovery(item: RecoverableTranscript) -> None:
    item.journal_path.unlink(missing_ok=True)


def _read_entries(path: Path) -> list[TranscriptEntry]:
    entries: list[TranscriptEntry] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return entries
    for line in lines:
        try:
            raw = json.loads(line)
            raw["created_at"] = datetime.fromisoformat(str(raw["created_at"]))
            raw["words"] = [
                word if isinstance(word, TranscriptWord) else TranscriptWord(**word)
                for word in raw.get("words", [])
            ]
            entries.append(TranscriptEntry(**raw))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return entries
