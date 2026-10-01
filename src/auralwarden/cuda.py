from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


_DLL_DIRECTORY_HANDLES: list[object] = []
_NVIDIA_COMPONENTS = ("cublas", "cudnn")


def _default_search_roots() -> list[Path]:
    from auralwarden.paths import data_dir

    roots = [Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"]
    roots.append(data_dir() / "runtime" / "components" / "cuda-12.9")
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.extend(
            [
                Path(bundle_root) / "nvidia",
                Path(bundle_root),
            ]
        )
    executable_root = Path(sys.executable).resolve().parent
    roots.extend([executable_root / "nvidia", executable_root])
    return roots


def cuda_runtime_ready(directories: Iterable[Path]) -> bool:
    """A cuDNN loader alone does not make the Windows CUDA runtime usable."""
    roots = list(directories)
    return all(any((root / name).is_file() for root in roots)
               for name in ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"))


def find_nvidia_bin_directories(
    search_roots: Iterable[Path] | None = None,
) -> list[Path]:
    """Find project-local NVIDIA runtime directories without loading CUDA."""

    found: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots or _default_search_roots():
        root = Path(root).resolve()
        candidates = [root / component / "bin" for component in _NVIDIA_COMPONENTS]
        candidates.append(root)
        for candidate in candidates:
            if not candidate.is_dir() or candidate in seen:
                continue
            if any(
                path
                for pattern in ("cublas*.dll", "cudnn*.dll")
                for path in candidate.glob(pattern)
            ):
                seen.add(candidate)
                found.append(candidate)
    return found


def configure_cuda_dll_search_paths(
    search_roots: Iterable[Path] | None = None,
) -> list[Path]:
    """Expose project-local CUDA DLLs only to the current Windows process."""

    if sys.platform != "win32":
        return []
    directories = find_nvidia_bin_directories(search_roots)
    current_path = os.environ.get("PATH", "")
    existing = current_path.split(os.pathsep) if current_path else []
    new_entries = [str(path) for path in directories if str(path) not in existing]
    if new_entries:
        os.environ["PATH"] = os.pathsep.join(new_entries + existing)

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if callable(add_dll_directory):
        registered = {
            str(getattr(handle, "path", "")) for handle in _DLL_DIRECTORY_HANDLES
        }
        for path in directories:
            if str(path) not in registered:
                _DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(path)))
    return directories
