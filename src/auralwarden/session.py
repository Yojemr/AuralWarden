from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from auralwarden.models import DetectionEvent, EngineEvent, TranscriptEntry
from auralwarden.filenames import date_time_label, readable_name, unique_path


class SessionWorkspace:
    def __init__(self, root: Path, source: str, title: str = "") -> None:
        self.started_at = datetime.now()
        self.file_stamp = date_time_label(self.started_at)
        parsed = urlparse(source)
        source_fallback = parsed.hostname or Path(source).stem
        display_title = readable_name(title or source_fallback, "Transmisión")
        self.path = unique_path(root / f"{self.file_stamp} - {display_title}")
        self.path.mkdir(parents=True, exist_ok=False)
        self.events_path = self.path / "events.jsonl"
        self.transcript_recovery_path = self.path / "transcript-recovery.jsonl"
        self.metadata_path = self.path / "session.json"
        self.error_details_path = self.path / "error-details.log"
        self.recordings_dir = self.path / "recordings"
        self.clips_dir = self.path / "clips"
        self.audio_clips_dir = self.clips_dir / "audio"
        self.video_clips_dir = self.clips_dir / "video"
        self.transcripts_dir = self.path / "transcripts"
        self.video_buffer_dir = self.path / ".video-buffer"
        self._lock = RLock()
        self._metadata: dict[str, Any] = {
            "schema_version": 1,
            "source": source,
            "title": title,
            "started_at": self.started_at.isoformat(),
            "status": "starting",
        }
        self.update_metadata()

    @property
    def recording_path(self) -> Path:
        return self.recordings_dir / f"{self.file_stamp} - Audio completo.wav"

    @property
    def transcript_text_path(self) -> Path:
        return self.transcripts_dir / f"{self.file_stamp} - Transcripcion.txt"

    @property
    def transcript_json_path(self) -> Path:
        return self.transcripts_dir / f"{self.file_stamp} - Transcripcion.json"

    @property
    def full_video_path(self) -> Path:
        return self.recordings_dir / f"{self.file_stamp} - Video completo.mp4"

    def update_metadata(self, **changes: Any) -> None:
        with self._lock:
            self._metadata.update(changes)
            temporary = self.metadata_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.metadata_path)

    def append_engine_event(self, event: EngineEvent) -> None:
        self._append_json_line(event.to_dict())

    def append_detection(self, event: DetectionEvent, action: str) -> None:
        payload = asdict(event)
        payload["first_detected_at"] = event.first_detected_at.isoformat()
        payload["last_detected_at"] = event.last_detected_at.isoformat()
        self._append_json_line({"kind": "hotword_record", "action": action, **payload})

    def append_transcript_entry(self, entry: TranscriptEntry) -> None:
        payload = asdict(entry)
        payload["created_at"] = entry.created_at.isoformat()
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.transcript_recovery_path.open("a", encoding="utf-8") as output:
                output.write(line)
                output.flush()

    def clear_transcript_recovery(self) -> None:
        self.transcript_recovery_path.unlink(missing_ok=True)

    def write_error_details(self, details: str) -> None:
        """Keep local diagnostic details beside a failed session."""
        with self._lock:
            self.error_details_path.write_text(details, encoding="utf-8")

    def _append_json_line(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as output:
                output.write(line)
