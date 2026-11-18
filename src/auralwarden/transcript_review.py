from __future__ import annotations

import re
from dataclasses import dataclass

from auralwarden.media_review import finite_time, parse_time
from auralwarden.models import TranscriptEntry
from auralwarden.transcript import group_transcript_entries


@dataclass(frozen=True)
class TranscriptSpan:
    start: int
    end: int
    seconds: float


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def review_text(entries: list[TranscriptEntry]) -> tuple[str, list[TranscriptSpan]]:
    clean = [entry for entry in entries if entry.text.strip()]
    paragraphs = group_transcript_entries(clean)
    if not paragraphs:
        return "Esta transcripción no contiene fragmentos legibles.", []
    blocks, spans, offset, index = [], [], 0, 0
    for paragraph in paragraphs:
        header = f"[{paragraph.display_timestamp()}] {paragraph.speaker_id}\n"
        block = header
        for part in paragraph.parts:
            if block != header:
                block += " "
            entry = clean[index]
            start = offset + utf16_length(block)
            spans.append(TranscriptSpan(start, start + utf16_length(part), finite_time(entry.elapsed_seconds)))
            block += part
            index += 1
        if paragraph.hotwords:
            block += f"\nHotwords: {', '.join(paragraph.hotwords)}"
        blocks.append(block)
        offset += utf16_length(block + "\n\n")
    return "\n\n".join(blocks), spans


def text_spans(text: str) -> list[TranscriptSpan]:
    matches = list(re.finditer(r"(?m)^\[(\d{1,5}:[0-5]\d:[0-5]\d(?:[.,]\d{1,3})?)\]", text))
    starts, cursor, units = [], 0, 0
    for match in matches:
        units += utf16_length(text[cursor:match.start()])
        cursor = match.start()
        starts.append(units)
    total = units + utf16_length(text[cursor:])
    spans = []
    for index, match in enumerate(matches):
        end = starts[index + 1] if index + 1 < len(starts) else total
        spans.append(TranscriptSpan(starts[index], end, parse_time(match[1])))
    return spans
