from __future__ import annotations

import shutil
import hashlib
import tarfile
import urllib.request
import threading
from pathlib import Path
from typing import Callable

from auralwarden.model_installer import _check_cancel


SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/"
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)
SEGMENTATION_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
EMBEDDING_SHA256 = "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"


def _download(url: str, destination: Path, *, sha256: str, max_bytes: int,
              cancel: threading.Event | None = None,
              progress: Callable[[int, int, str], None] | None = None) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            digest = hashlib.sha256()
            total = 0
            with temporary.open("wb") as output:
                while block := response.read(64 * 1024):
                    if cancel is not None:
                        _check_cancel(cancel)
                    total += len(block)
                    if total > max_bytes:
                        raise RuntimeError("El modelo descargado supera el tamaño permitido.")
                    digest.update(block)
                    output.write(block)
                    if progress is not None:
                        progress(total, max_bytes, "Descargando modelos de hablantes…")
        if digest.hexdigest() != sha256.casefold():
            raise RuntimeError("El modelo descargado no coincide con su SHA-256 esperado.")
        if cancel is not None:
            _check_cancel(cancel)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_diarization_models(output_dir: Path, *, force: bool = False,
                                cancel: threading.Event | None = None,
                                progress: Callable[[int, int, str], None] | None = None) -> dict[str, Path]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    segmentation = output_dir / "segmentation.onnx"
    embedding = output_dir / "embedding.onnx"
    license_path = output_dir / "segmentation-LICENSE"
    archive = output_dir / "segmentation.tar.bz2.download"

    if force or not segmentation.is_file():
        _download(SEGMENTATION_URL, archive, sha256=SEGMENTATION_SHA256, max_bytes=10_000_000,
                  cancel=cancel, progress=progress)
        try:
            with tarfile.open(archive, "r:bz2") as package:
                model_members = [
                    member
                    for member in package.getmembers()
                    if member.isfile() and member.name.endswith("/model.onnx")
                ]
                if len(model_members) != 1:
                    raise RuntimeError("El paquete de segmentación no contiene el modelo esperado.")
                source = package.extractfile(model_members[0])
                if source is None:
                    raise RuntimeError("No se pudo leer el modelo de segmentación.")
                temporary = segmentation.with_suffix(".onnx.part")
                with source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                temporary.replace(segmentation)

                license_members = [
                    member
                    for member in package.getmembers()
                    if member.isfile() and member.name.endswith("/LICENSE")
                ]
                if license_members:
                    license_source = package.extractfile(license_members[0])
                    if license_source is not None:
                        with license_source, license_path.open("wb") as output:
                            shutil.copyfileobj(license_source, output)
        finally:
            archive.unlink(missing_ok=True)
            segmentation.with_suffix(".onnx.part").unlink(missing_ok=True)

    if force or not embedding.is_file():
        _download(EMBEDDING_URL, embedding, sha256=EMBEDDING_SHA256, max_bytes=45_000_000,
                  cancel=cancel, progress=progress)
    return {"segmentation": segmentation, "embedding": embedding}
