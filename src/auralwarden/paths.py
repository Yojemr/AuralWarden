from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_NAME = "AuralWarden"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def runtime_executable(name: str) -> str | None:
    """Find an executable bundled beside the app before consulting PATH."""
    filename = name if name.lower().endswith(".exe") else f"{name}.exe"
    candidates = [application_root() / filename]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / filename)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return shutil.which(name)


def portable_mode() -> bool:
    value = os.environ.get("AURALWARDEN_PORTABLE", "").strip().lower()
    return value in {"1", "true", "yes", "on"} or (application_root() / "portable.flag").exists()


def data_dir() -> Path:
    override = os.environ.get("AURALWARDEN_DATA_DIR")
    if override:
        path = Path(override).expanduser().resolve()
    elif portable_mode():
        path = application_root() / "data"
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def runtime_status_path() -> Path:
    return data_dir() / "runtime-status.json"


def speaker_profiles_path() -> Path:
    return data_dir() / "speaker-profiles.json"


def presets_path() -> Path:
    return data_dir() / "presets.json"


def alert_history_path() -> Path:
    return data_dir() / "alert-history.json"


def local_control_credentials_path() -> Path:
    return data_dir() / "local-control.json"


def local_control_audit_path() -> Path:
    return data_dir() / "local-control-audit.json"


def silent_audio_state_path() -> Path:
    return data_dir() / "silent-audio-state.json"


def transcripts_dir() -> Path:
    path = data_dir() / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clips_dir() -> Path:
    path = data_dir() / "clips"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recordings_dir() -> Path:
    path = data_dir() / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sessions_dir() -> Path:
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def diarization_models_dir() -> Path:
    path = data_dir() / "models" / "diarization"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
