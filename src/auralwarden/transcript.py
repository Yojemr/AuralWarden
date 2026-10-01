from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from auralwarden.models import TranscriptEntry


PARAGRAPH_PAUSE_SECONDS = 8.0
PARAGRAPH_MAX_SECONDS = 90.0
PARAGRAPH_MAX_CHARACTERS = 900


@dataclass(slots=True)
class TranscriptParagraph:
    elapsed_seconds: float
    end_seconds: float
    speaker_id: str
    parts: list[str] = field(default_factory=list)
    hotwords: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.parts)

    def display_timestamp(self) -> str:
        total = max(0, int(self.elapsed_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def group_transcript_entries(
    entries: Iterable[TranscriptEntry],
) -> list[TranscriptParagraph]:
    paragraphs: list[TranscriptParagraph] = []
    for entry in entries:
        text = " ".join(entry.text.split())
        if not text:
            continue
        entry_end = max(entry.elapsed_seconds, entry.end_seconds or entry.elapsed_seconds)
        paragraph = paragraphs[-1] if paragraphs else None
        if paragraph is None or not can_extend_paragraph(
            paragraph.speaker_id,
            paragraph.elapsed_seconds,
            paragraph.end_seconds,
            len(paragraph.text),
            entry.speaker_id,
            entry.elapsed_seconds,
        ):
            paragraph = TranscriptParagraph(
                elapsed_seconds=entry.elapsed_seconds,
                end_seconds=entry_end,
                speaker_id=entry.speaker_id,
            )
            paragraphs.append(paragraph)
        paragraph.parts.append(text)
        paragraph.elapsed_seconds = min(
            paragraph.elapsed_seconds, entry.elapsed_seconds
        )
        paragraph.end_seconds = max(paragraph.end_seconds, entry_end)
        for phrase in entry.hotwords:
            if phrase and phrase.casefold() not in {
                existing.casefold() for existing in paragraph.hotwords
            }:
                paragraph.hotwords.append(phrase)
    return paragraphs


def can_extend_paragraph(
    current_speaker: str,
    paragraph_start: float,
    previous_end: float,
    current_characters: int,
    next_speaker: str,
    next_start: float,
) -> bool:
    if current_speaker != next_speaker:
        return False
    if next_start - previous_end > PARAGRAPH_PAUSE_SECONDS:
        return False
    if next_start - paragraph_start >= PARAGRAPH_MAX_SECONDS:
        return False
    return current_characters < PARAGRAPH_MAX_CHARACTERS


class TranscriptBuffer:
    def __init__(self) -> None:
        self.entries: list[TranscriptEntry] = []
        self.dirty = False

    def add(self, entry: TranscriptEntry) -> None:
        self.entries.append(entry)
        self.dirty = True

    def clear(self) -> None:
        self.entries.clear()
        self.dirty = False

    def rename_speaker(self, speaker_id: str, display_name: str) -> None:
        for entry in self.entries:
            if entry.speaker_id == speaker_id:
                entry.speaker_id = display_name
        self.dirty = bool(self.entries)

    def export_text(self, path: Path, title: str = "AuralWarden session") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [title, f"Exported: {datetime.now().isoformat(timespec='seconds')}", ""]
        for paragraph in group_transcript_entries(self.entries):
            marker = (
                f"  [hotwords: {', '.join(paragraph.hotwords)}]"
                if paragraph.hotwords
                else ""
            )
            lines.append(
                f"[{paragraph.display_timestamp()}] {paragraph.speaker_id}: "
                f"{paragraph.text}{marker}"
            )
            lines.append("")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.dirty = False

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for entry in self.entries:
            item = asdict(entry)
            item["created_at"] = entry.created_at.isoformat()
            item["timestamp"] = entry.display_timestamp()
            payload.append(item)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
