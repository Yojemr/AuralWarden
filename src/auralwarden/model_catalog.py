from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from auralwarden.paths import application_root, data_dir


MODEL_MARKERS = ("config.json", "model.bin", "tokenizer.json")


@dataclass(frozen=True, slots=True)
class LocalWhisperModel:
    name: str
    path: Path
    source: str


def is_whisper_model_directory(path: Path) -> bool:
    return path.is_dir() and all((path / marker).is_file() for marker in MODEL_MARKERS)


def model_search_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    override = os.environ.get("AURALWARDEN_MODELS_DIR", "").strip()
    if override:
        roots.append(Path(override).expanduser())

    try:
        roots.append(data_dir() / "models")
    except OSError:
        pass
    app_root = application_root()
    for ancestor in (app_root, *app_root.parents[:3]):
        roots.append(ancestor / "data" / "models")
    roots.append(Path(__file__).resolve().parents[2] / "data" / "models")
    roots.append(Path.cwd() / "data" / "models")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root.absolute()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return tuple(unique)


def discover_local_whisper_models() -> list[LocalWhisperModel]:
    discovered: list[LocalWhisperModel] = []
    seen: set[str] = set()

    def add(path: Path, source: str, name: str | None = None) -> None:
        if not is_whisper_model_directory(path):
            return
        resolved = path.resolve()
        key = str(resolved).casefold()
        if key in seen:
            return
        seen.add(key)
        discovered.append(LocalWhisperModel(name or resolved.name, resolved, source))

    for root in model_search_roots():
        add(root, "configured")
        if not root.is_dir():
            continue
        try:
            children = tuple(root.iterdir())
        except OSError:
            continue
        for child in children:
            add(child, "auralwarden")

    for cache_root in _hugging_face_hub_roots():
        if not cache_root.is_dir():
            continue
        try:
            repositories = tuple(cache_root.glob("models--*"))
        except OSError:
            continue
        for repository in repositories:
            snapshots = repository / "snapshots"
            if not snapshots.is_dir():
                continue
            repository_name = repository.name.removeprefix("models--").replace("--", "/")
            try:
                candidates = tuple(snapshots.iterdir())
            except OSError:
                continue
            for candidate in candidates:
                add(candidate, "huggingface", repository_name)

    return sorted(
        discovered,
        key=lambda item: (
            0 if _normalized_model_name(item.name) == "large-v3-turbo" else 1,
            item.name.casefold(),
            str(item.path).casefold(),
        ),
    )


def resolve_local_whisper_model(
    requested: str, catalog: Iterable[LocalWhisperModel] | None = None
) -> Path | None:
    value = requested.strip()
    if value:
        candidate = Path(value).expanduser()
        if is_whisper_model_directory(candidate):
            return candidate.resolve()

    models = list(catalog) if catalog is not None else discover_local_whisper_models()
    if not models:
        return None
    normalized = _normalized_model_name(value)
    requested_names = {normalized}
    if value:
        requested_names.add(_normalized_model_name(Path(value).name))
    if normalized in {"", "auto", "automatico", "automatic"}:
        preferred = next(
            (
                item
                for item in models
                if _normalized_model_name(item.name) == "large-v3-turbo"
            ),
            models[0],
        )
        return preferred.path

    for model in models:
        names = {
            _normalized_model_name(model.name),
            _normalized_model_name(model.path.name),
        }
        if requested_names & names:
            return model.path
    return None


def _normalized_model_name(value: str) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    for prefix in (
        "faster-whisper-",
        "mobiuslabsgmbh/",
        "systran/",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def _hugging_face_hub_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    hf_home = os.environ.get("HF_HOME", "").strip()
    if hf_home:
        roots.append(Path(hf_home).expanduser() / "hub")
    cache_home = os.environ.get("HUGGINGFACE_HUB_CACHE", "").strip()
    if cache_home:
        roots.append(Path(cache_home).expanduser())
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return tuple(roots)
