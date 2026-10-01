from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from auralwarden.paths import alert_history_path


class AlertHistoryStore:
    def __init__(self, path: Path | None = None, max_records: int = 1000) -> None:
        self.path = path or alert_history_path()
        self.max_records = max(10, max_records)

    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        rows = payload.get("alerts", []) if isinstance(payload, dict) else []
        return [dict(item) for item in rows if isinstance(item, dict)]

    def add_detection(
        self,
        payload: dict[str, Any],
        *,
        source_title: str = "",
        session_path: Path | None = None,
    ) -> None:
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            return
        records = self.records()
        existing = next(
            (item for item in records if str(item.get("event_id")) == event_id),
            None,
        )
        values = {
            "event_id": event_id,
            "detected_at": str(payload.get("detected_at") or datetime.now().isoformat(timespec="seconds")),
            "phrase": str(payload.get("phrase") or "Coincidencia"),
            "score": float(payload.get("score") or 0.0),
            "elapsed_seconds": float(payload.get("elapsed_seconds") or 0.0),
            "context": str(payload.get("context") or ""),
            "matched_text": str(payload.get("matched_text") or ""),
            "speaker_id": str(payload.get("speaker_id") or ""),
            "source": str(source_title or payload.get("source") or ""),
            "session_path": str(session_path or ""),
            "audio_clip": "",
            "video_clip": "",
        }
        if existing is None:
            records.insert(0, values)
        else:
            audio = str(existing.get("audio_clip") or "")
            video = str(existing.get("video_clip") or "")
            existing.update(values)
            existing["audio_clip"] = audio
            existing["video_clip"] = video
        self._write(records[: self.max_records])

    def attach_clip(self, event_id: str, path: str, media_type: str) -> None:
        records = self.records()
        record = next(
            (item for item in records if str(item.get("event_id")) == event_id),
            None,
        )
        if record is None:
            return
        key = "video_clip" if media_type == "video/mp4" else "audio_clip"
        record[key] = path
        self._write(records)

    def clear(self) -> None:
        self._write([])

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": 1, "alerts": records},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)
