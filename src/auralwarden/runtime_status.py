from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from auralwarden import __version__
from auralwarden.models import SessionState
from auralwarden.paths import runtime_status_path


class RuntimeStatusStore:
    """Publishes UI state without treating an open process as active monitoring."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or runtime_status_path()

    def write(
        self,
        state: SessionState,
        *,
        application_open: bool = True,
        source: str = "",
        detail: str = "",
        session_path: Path | None = None,
    ) -> None:
        monitoring = state in {
            SessionState.STARTING,
            SessionState.RUNNING,
            SessionState.WAITING,
            SessionState.RECONNECTING,
            SessionState.STOPPING,
        }
        payload: dict[str, Any] = {
            "application_open": application_open,
            "monitoring": monitoring,
            "state": state.value,
            "detail": detail,
            "source": source,
            "session_path": str(session_path) if session_path else "",
            "process_id": os.getpid(),
            "version": __version__,
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
