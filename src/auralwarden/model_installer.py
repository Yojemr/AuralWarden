from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class DownloadCancelled(Exception):
    pass


Progress = Callable[[int, int, str], None]


def model_manifest() -> dict:
    return json.loads(Path(__file__).with_name("model_downloads.json").read_text(encoding="utf-8"))


def initialize_data_layout(root: Path) -> None:
    for name in ("models", "sessions", "transcripts", "clips/audio", "clips/video", "recordings", "runtime/components"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise DownloadCancelled("Descarga cancelada. Los modelos existentes se conservaron.")


class _HttpsRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ValueError("La descarga intentó redirigir fuera de HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_download(url: str):
    if urlparse(url).scheme != "https":
        raise ValueError("Solo se permiten descargas HTTPS.")
    # A dedicated opener does not inherit Hugging Face tokens or browser cookies.
    return urllib.request.build_opener(_HttpsRedirects()).open(url, timeout=15)


def _valid_file(path: Path, spec: dict, cancel: threading.Event) -> bool:
    if not path.is_file() or path.stat().st_size != spec["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest() == spec["sha256"]


def install_whisper_model(
    name: str, models_root: Path, *, cancel: threading.Event | None = None,
    progress: Progress | None = None,
) -> Path:
    manifest = model_manifest()
    if name not in manifest:
        raise ValueError("El modelo no pertenece al catálogo verificado.")
    model = manifest[name]
    cancel = cancel or threading.Event()
    progress = progress or (lambda *_: None)
    _check_cancel(cancel)
    models_root = models_root.resolve()
    models_root.mkdir(parents=True, exist_ok=True)
    target = models_root / name
    files = model["files"]
    total = sum(item["size"] for item in files)
    if target.exists():
        progress(0, total, "Verificando el modelo existente…")
        if all(_valid_file(target / item["name"], item, cancel) for item in files):
            progress(total, total, "Modelo existente verificado")
            return target
        raise FileExistsError(
            "Ya existe una carpeta con ese nombre, pero no coincide con esta revisión. "
            "Se ha conservado intacta. Puedes elegirla manualmente si es un modelo válido."
        )
    if shutil.disk_usage(models_root).free < total + 100 * 1024**2:
        raise OSError("No hay espacio suficiente para este modelo y 100 MiB de margen.")
    staging_root = models_root / ".downloads"
    staging_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=staging_root) as temporary:
        staging = Path(temporary)
        completed = 0
        last_progress = 0.0
        for spec in files:
            filename = spec["name"]
            if Path(filename).name != filename or "/" in filename or "\\" in filename:
                raise ValueError("Nombre de archivo no permitido en el catálogo.")
            _check_cancel(cancel)
            progress(completed, total, f"Descargando {filename}…")
            url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{filename}"
            digest = hashlib.sha256()
            downloaded = 0
            with _open_download(url) as response, (staging / filename).open("xb") as output:
                while True:
                    _check_cancel(cancel)
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    downloaded += len(block)
                    if downloaded > spec["size"]:
                        raise ValueError("La descarga supera el tamaño verificado.")
                    digest.update(block)
                    output.write(block)
                    now = time.monotonic()
                    if now - last_progress >= 0.1:
                        progress(completed + downloaded, total, f"Descargando {filename}…")
                        last_progress = now
            if downloaded != spec["size"] or digest.hexdigest() != spec["sha256"]:
                raise ValueError("La descarga está incompleta o no coincide con su SHA-256. Pulsa Reintentar.")
            completed += downloaded
        _check_cancel(cancel)
        # A rename publishes the complete directory at once; never overwrite a local model.
        if target.exists():
            raise FileExistsError("Otro instalador creó el modelo. No se ha sobrescrito.")
        staging.rename(target)
    progress(total, total, "Modelo instalado y verificado")
    return target
