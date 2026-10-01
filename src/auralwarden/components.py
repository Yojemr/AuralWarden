from __future__ import annotations

import hashlib
import io
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from auralwarden.paths import data_dir


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    component_id: str
    version: str
    url: str
    sha256: str
    executable_names: tuple[str, ...]


WHISPER_CPP_CPU = ComponentSpec(
    component_id="whisper-cpp-cpu",
    version="1.9.3",
    url=(
        "https://github.com/ggml-org/whisper.cpp/releases/download/"
        "v1.9.3/whisper-bin-x64.zip"
    ),
    sha256="c2a4b60edb11f7e11a9191ffb50929535527d4d91c9903dbe3e554583bbbc63d",
    executable_names=("whisper-cli.exe", "main.exe"),
)


class ComponentInstallError(RuntimeError):
    pass


class ComponentManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir() / "runtime" / "components"

    def component_dir(self, spec: ComponentSpec) -> Path:
        return self.root / spec.component_id / spec.version

    def find_executable(self, spec: ComponentSpec) -> Path | None:
        root = self.component_dir(spec)
        for name in spec.executable_names:
            matches = tuple(root.rglob(name)) if root.is_dir() else ()
            if matches:
                return matches[0].resolve()
        return None

    def install(
        self,
        spec: ComponentSpec,
        *,
        opener: Callable[[str], BinaryIO] | None = None,
    ) -> Path:
        opener = opener or urllib.request.urlopen
        target = self.component_dir(spec)
        staging = target.with_name(f".{target.name}.installing")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            with opener(spec.url) as response:
                payload = response.read()
            digest = hashlib.sha256(payload).hexdigest()
            if digest.casefold() != spec.sha256.casefold():
                raise ComponentInstallError("La descarga no coincide con su firma SHA-256.")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                destination = staging.resolve()
                for member in archive.infolist():
                    resolved = (staging / member.filename).resolve()
                    if destination != resolved and destination not in resolved.parents:
                        raise ComponentInstallError("El componente contiene una ruta insegura.")
                archive.extractall(staging)
            executable = next(
                (
                    path
                    for name in spec.executable_names
                    for path in staging.rglob(name)
                ),
                None,
            )
            if executable is None:
                raise ComponentInstallError("El componente no contiene su ejecutable.")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
            installed = self.find_executable(spec)
            if installed is None:
                raise ComponentInstallError("No se pudo validar el componente instalado.")
            return installed
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
