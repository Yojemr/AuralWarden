from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4


def validated_seconds(value) -> float:
    if type(value) not in (int, float):
        raise ValueError("Indica un tiempo numérico válido.")
    try:
        seconds = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("El tiempo indicado no se puede representar.") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("El tiempo debe ser finito y no negativo.")
    return seconds


def bookmark_scope(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if resolved.is_file():
        session = resolved.parent.parent if resolved.parent.name.casefold() == "transcripts" else resolved.parent
        if (session / "session.json").is_file():
            resolved = session
    return str(resolved)


class BookmarkStore:
    """Explicit local annotations; original transcripts are never rewritten."""

    MAX_ITEMS = 1000
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, path: Path):
        self.path = path
        self._lock = RLock()

    def _read(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > self.MAX_BYTES:
            raise ValueError("El archivo de marcadores supera el tamaño permitido.")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("bookmarks") if isinstance(raw, dict) else None
        if not isinstance(items, list) or len(items) > self.MAX_ITEMS:
            raise ValueError("El archivo de marcadores no es válido.")
        for item in items:
            if (not isinstance(item, dict)
                    or not all(isinstance(item.get(key), str) for key in ("id", "scope", "note", "created_at"))
                    or len(item["note"]) > 1000 or len(item["scope"]) > 1024):
                raise ValueError("Hay un marcador no válido; no se modificó el archivo.")
            validated_seconds(item.get("elapsed_seconds"))
        return items

    def records(self, scope: Path):
        key = bookmark_scope(scope).casefold()
        with self._lock:
            return sorted((dict(item) for item in self._read() if item["scope"].casefold() == key),
                          key=lambda item: item["elapsed_seconds"])

    def add(self, scope: Path, elapsed_seconds: float, note: str):
        elapsed = validated_seconds(elapsed_seconds)
        text = str(note).strip()
        key = bookmark_scope(scope)
        if not text or len(text) > 1000 or len(key) > 1024:
            raise ValueError("Indica una nota de hasta 1.000 caracteres y un tiempo válido.")
        item = {"id": uuid4().hex, "scope": key, "elapsed_seconds": elapsed, "note": text,
                "created_at": datetime.now().isoformat(timespec="seconds")}
        with self._lock:
            items = self._read()
            if len(items) >= self.MAX_ITEMS:
                raise ValueError("Se alcanzó el límite de 1.000 marcadores. Elimina alguno para continuar.")
            self._write([*items, item])
        return dict(item)

    def delete(self, scope: Path, bookmark_id: str):
        key = bookmark_scope(scope).casefold()
        with self._lock:
            items = self._read()
            self._write([item for item in items if not (item["id"] == bookmark_id and item["scope"].casefold() == key)])

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"schema": 1, "bookmarks": items}, ensure_ascii=False, allow_nan=False, indent=2)
        if len(text.encode("utf-8")) > self.MAX_BYTES:
            raise ValueError("El archivo de marcadores supera el tamaño permitido.")
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.path)
