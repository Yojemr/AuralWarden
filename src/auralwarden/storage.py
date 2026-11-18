from __future__ import annotations

import os
import json
import stat
import time
from dataclasses import dataclass
from pathlib import Path


LABELS = {"models": "Modelos", "components": "Componentes opcionales", "clips": "Clips",
          "recordings": "Grabaciones completas", "transcripts": "Transcripciones",
          "recovery": "Recuperación de vídeo", "other": "Configuración y otros"}


@dataclass(frozen=True)
class StorageFile:
    relative: str
    category: str
    size: int
    modified_ns: int
    inode: int


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _category(relative: Path) -> str:
    parts = relative.parts
    if parts[0] == "models":
        return "models"
    if parts[:2] == ("runtime", "components"):
        return "components"
    if ".video-buffer" in parts:
        return "recovery"
    for category in ("clips", "recordings", "transcripts"):
        if category in parts[:-1]:
            return category
    return "other"


def scan_storage(root: Path, *, max_files=20000, max_seconds=15, cancelled=lambda: False):
    root = Path(root).absolute()
    if _linked(root):
        raise ValueError("No se examinan carpetas de datos enlazadas.")
    files, complete = [], True
    deadline = time.monotonic() + max_seconds
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as children:
                for child in children:
                    if cancelled() or time.monotonic() > deadline or len(files) >= max_files:
                        return files, False
                    path = Path(child.path)
                    if _linked(path):
                        complete = False
                        continue
                    if child.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif child.is_file(follow_symlinks=False):
                        info = path.stat(follow_symlinks=False)
                        relative = path.relative_to(root)
                        files.append(StorageFile(str(relative), _category(relative), info.st_size,
                                                 info.st_mtime_ns, info.st_ino))
        except OSError:
            complete = False
    return files, complete


def validate_storage_file(root: Path, item: StorageFile) -> Path:
    root = Path(root).absolute()
    relative = Path(item.relative)
    if relative.is_absolute() or relative.drive or relative.root or not relative.parts or any(p in ("..", ".") for p in relative.parts):
        raise ValueError("Ruta fuera de los datos de AuralWarden.")
    if item.category not in {"clips", "recordings", "transcripts"} or _category(relative) != item.category:
        raise ValueError("Este archivo está protegido. Usa su herramienta específica para administrarlo.")
    candidate = root
    if _linked(root):
        raise ValueError("La carpeta de datos cambió.")
    for part in relative.parts:
        candidate = candidate / part
        if _linked(candidate):
            raise ValueError("La ruta contiene un enlace; no se modifica.")
    if relative.parts[0] == "sessions" and len(relative.parts) >= 3:
        metadata = root / relative.parts[0] / relative.parts[1] / "session.json"
        if _linked(metadata) or metadata.stat().st_size > 1024 * 1024:
            raise ValueError("No se pudo verificar que la sesión haya terminado.")
        raw = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("status") not in {"stopped", "failed"}:
            raise ValueError("Esta sesión no está finalizada; se conservan sus archivos.")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Ruta fuera de los datos de AuralWarden.")
    info = candidate.stat()
    if not candidate.is_file() or (info.st_size, info.st_mtime_ns, info.st_ino) != (item.size, item.modified_ns, item.inode):
        raise ValueError("El archivo cambió desde el análisis. Actualiza la lista.")
    return candidate
