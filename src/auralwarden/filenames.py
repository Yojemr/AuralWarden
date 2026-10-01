from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def readable_name(value: str, fallback: str = "AuralWarden") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned[:90] or fallback


def date_time_label(value: datetime) -> str:
    return value.strftime("%Y-%m-%d_%H-%M-%S")


def elapsed_label(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}h{minutes:02d}m{secs:02d}s"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"No fue posible elegir un nombre disponible para {path.name}")
