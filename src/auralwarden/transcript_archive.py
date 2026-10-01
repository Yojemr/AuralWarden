from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from auralwarden.models import TranscriptEntry, TranscriptWord
from auralwarden.transcript import group_transcript_entries


@dataclass(frozen=True, slots=True)
class ArchivedTranscript:
    path: Path
    title: str
    started_at: str = ""
    session_path: Path | None = None

    @property
    def display_date(self) -> str:
        if self.started_at:
            try:
                return datetime.fromisoformat(self.started_at).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except OSError:
            return "Sin fecha"

    @property
    def label(self) -> str:
        return f"{self.title}  ·  {self.display_date}"


def discover_archived_transcripts(root: Path) -> list[ArchivedTranscript]:
    if not root.is_dir():
        return []
    candidates: dict[Path, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.casefold()
        if lower.endswith(" - transcripcion.json"):
            candidates[_session_key(path)] = path
        elif lower.endswith(" - transcripcion.txt"):
            candidates.setdefault(_session_key(path), path)
        elif lower == "transcript-recovery.jsonl":
            candidates.setdefault(_session_key(path), path)
    records = [_archive_record(path) for path in candidates.values()]
    return sorted(records, key=lambda item: (item.started_at, item.path.name), reverse=True)


def load_archived_transcript(path: Path) -> tuple[str, list[TranscriptEntry]]:
    resolved = path.expanduser().resolve()
    suffix = resolved.suffix.casefold()
    if suffix == ".txt":
        return resolved.read_text(encoding="utf-8-sig"), []
    if suffix == ".jsonl":
        raw_items: list[Any] = []
        for line in resolved.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                raw_items.append(json.loads(line))
    elif suffix == ".json":
        raw_items = json.loads(resolved.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_items, list):
            raise ValueError("La transcripción JSON debe contener una lista de fragmentos.")
    else:
        raise ValueError("Formato no compatible. Selecciona un TXT, JSON o JSONL.")
    entries = [_entry_from_dict(item) for item in raw_items if isinstance(item, dict)]
    return render_archived_transcript(entries), entries


def render_archived_transcript(entries: Iterable[TranscriptEntry]) -> str:
    paragraphs = group_transcript_entries(entries)
    if not paragraphs:
        return "Esta transcripción no contiene fragmentos legibles."
    blocks: list[str] = []
    for paragraph in paragraphs:
        hotwords = (
            f"\nHotwords: {', '.join(paragraph.hotwords)}"
            if paragraph.hotwords
            else ""
        )
        blocks.append(
            f"[{paragraph.display_timestamp()}] {paragraph.speaker_id}\n"
            f"{paragraph.text}{hotwords}"
        )
    return "\n\n".join(blocks)


def _archive_record(path: Path) -> ArchivedTranscript:
    session_path = _session_key(path)
    metadata_path = session_path / "session.json"
    metadata: dict[str, Any] = {}
    try:
        loaded = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            metadata = loaded
    except (OSError, ValueError, TypeError):
        pass
    title = " ".join(str(metadata.get("title") or "").split()).strip()
    if not title:
        title = session_path.name if session_path != path.parent else path.stem
    return ArchivedTranscript(
        path=path,
        title=title,
        started_at=str(metadata.get("started_at") or ""),
        session_path=session_path,
    )


def _session_key(path: Path) -> Path:
    if path.parent.name.casefold() == "transcripts":
        return path.parent.parent
    return path.parent


def _entry_from_dict(raw: dict[str, Any]) -> TranscriptEntry:
    words = []
    for item in raw.get("words") or []:
        if not isinstance(item, dict):
            continue
        try:
            words.append(
                TranscriptWord(
                    text=str(item.get("text") or ""),
                    start_seconds=float(item.get("start_seconds") or 0.0),
                    end_seconds=float(item.get("end_seconds") or 0.0),
                    probability=(
                        float(item["probability"])
                        if item.get("probability") is not None
                        else None
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    created_at = datetime.now()
    try:
        if raw.get("created_at"):
            created_at = datetime.fromisoformat(str(raw["created_at"]))
    except ValueError:
        pass
    return TranscriptEntry(
        elapsed_seconds=float(raw.get("elapsed_seconds") or 0.0),
        speaker_id=str(raw.get("speaker_id") or "Speaker 1"),
        text=str(raw.get("text") or ""),
        end_seconds=(
            float(raw["end_seconds"])
            if raw.get("end_seconds") is not None
            else None
        ),
        created_at=created_at,
        confirmed=bool(raw.get("confirmed", True)),
        hotwords=[str(item) for item in raw.get("hotwords") or [] if str(item)],
        confidence=(
            float(raw["confidence"])
            if raw.get("confidence") is not None
            else None
        ),
        source=str(raw.get("source") or "stt"),
        second_pass=bool(raw.get("second_pass", False)),
        refinement_reason=(
            str(raw["refinement_reason"])
            if raw.get("refinement_reason") is not None
            else None
        ),
        words=words,
        speaker_confidence=(
            float(raw["speaker_confidence"])
            if raw.get("speaker_confidence") is not None
            else None
        ),
        no_speech_probability=(
            float(raw["no_speech_probability"])
            if raw.get("no_speech_probability") is not None
            else None
        ),
    )
