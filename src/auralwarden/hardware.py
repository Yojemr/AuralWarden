from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from auralwarden.cuda import configure_cuda_dll_search_paths, cuda_runtime_ready
from auralwarden.paths import data_dir


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True, slots=True)
class GpuAdapter:
    name: str
    vendor: str
    memory_mb: int = 0


@dataclass(frozen=True, slots=True)
class HardwareCapabilities:
    physical_cores: int
    logical_cores: int
    memory_gb: float
    gpus: tuple[GpuAdapter, ...] = ()
    cuda_available: bool = False
    cuda_compute_types: tuple[str, ...] = ()
    whisper_cpp_executable: str = ""

    @property
    def nvidia_vram_mb(self) -> int:
        return max(
            (gpu.memory_mb for gpu in self.gpus if gpu.vendor == "nvidia"),
            default=0,
        )

    @property
    def has_nvidia_gpu(self) -> bool:
        return any(gpu.vendor == "nvidia" for gpu in self.gpus)

    @property
    def cuda_setup_recommended(self) -> bool:
        return self.has_nvidia_gpu and not self.cuda_available

    @property
    def preferred_cuda_model(self) -> str:
        return "large-v3-turbo" if self.nvidia_vram_mb >= 6_000 else "small"

    @property
    def has_cross_vendor_gpu(self) -> bool:
        return any(gpu.vendor in {"amd", "intel"} for gpu in self.gpus)


@dataclass(frozen=True, slots=True)
class InferencePlan:
    backend: str
    device: str
    compute_type: str
    model_candidates: tuple[str, ...]
    cpu_threads: int
    performance_mode: str
    reason: str
    whisper_cpp_executable: str = ""
    whisper_cpp_model: str = ""


def _gpu_vendor(name: str) -> str:
    normalized = name.casefold()
    if "nvidia" in normalized:
        return "nvidia"
    if "amd" in normalized or "radeon" in normalized:
        return "amd"
    if "intel" in normalized:
        return "intel"
    return "other"


def _windows_gpu_adapters() -> tuple[GpuAdapter, ...]:
    if os.name != "nt":
        return ()
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return ()
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
    ]
    nvidia_memory = _nvidia_memory_by_name()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
        raw = json.loads(result.stdout.strip() or "[]")
        rows = raw if isinstance(raw, list) else [raw]
        adapters = tuple(
            GpuAdapter(
                name=str(row.get("Name") or "GPU"),
                vendor=_gpu_vendor(str(row.get("Name") or "")),
                memory_mb=max(0, int(row.get("AdapterRAM") or 0) // (1024 * 1024)),
            )
            for row in rows
            if isinstance(row, dict)
        )
        if not nvidia_memory:
            return adapters
        memory_by_fold = {
            name.casefold(): memory for name, memory in nvidia_memory.items()
        }
        merged = tuple(
            GpuAdapter(
                name=adapter.name,
                vendor=adapter.vendor,
                memory_mb=(
                    memory_by_fold.get(adapter.name.casefold(), adapter.memory_mb)
                    if adapter.vendor == "nvidia"
                    else adapter.memory_mb
                ),
            )
            for adapter in adapters
        )
        known = {adapter.name.casefold() for adapter in merged}
        extras = tuple(
            GpuAdapter(name, "nvidia", memory)
            for name, memory in nvidia_memory.items()
            if name.casefold() not in known
        )
        return (*merged, *extras)
    except (OSError, ValueError, subprocess.SubprocessError):
        return tuple(
            GpuAdapter(name, "nvidia", memory)
            for name, memory in nvidia_memory.items()
        )


def _nvidia_memory_by_name() -> dict[str, int]:
    executable = shutil.which("nvidia-smi.exe") or shutil.which("nvidia-smi")
    if not executable:
        return {}
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
        detected: dict[str, int] = {}
        for line in result.stdout.splitlines():
            name, separator, memory = line.rpartition(",")
            if not separator:
                continue
            clean_name = name.strip()
            detected[clean_name] = max(0, int(memory.strip()))
        return detected
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def find_whisper_cpp_executable(explicit: str = "") -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
    try:
        roots = [data_dir() / "runtime" / "components"]
    except OSError:
        roots = []
    for root in roots:
        if not root.is_dir():
            continue
        for name in ("whisper-cli.exe", "main.exe", "whisper-cli"):
            matches = tuple(root.rglob(name))
            if matches:
                return str(matches[0].resolve())
    return ""


def detect_hardware(whisper_cpp_executable: str = "") -> HardwareCapabilities:
    try:
        import psutil

        physical = int(psutil.cpu_count(logical=False) or 1)
        logical = int(psutil.cpu_count(logical=True) or physical)
        memory_gb = float(psutil.virtual_memory().total / (1024**3))
    except ImportError:
        physical = max(1, os.cpu_count() or 1)
        logical = physical
        memory_gb = 0.0

    cuda_available = False
    compute_types: tuple[str, ...] = ()
    try:
        cuda_directories = configure_cuda_dll_search_paths()
        import ctranslate2

        runtime_ready = os.name != "nt" or cuda_runtime_ready(cuda_directories)
        cuda_available = runtime_ready and ctranslate2.get_cuda_device_count() > 0
        if cuda_available:
            compute_types = tuple(sorted(ctranslate2.get_supported_compute_types("cuda")))
    except (ImportError, RuntimeError):
        pass
    return HardwareCapabilities(
        physical_cores=physical,
        logical_cores=logical,
        memory_gb=memory_gb,
        gpus=_windows_gpu_adapters(),
        cuda_available=cuda_available,
        cuda_compute_types=compute_types,
        whisper_cpp_executable=find_whisper_cpp_executable(whisper_cpp_executable),
    )


def select_inference_plan(
    capabilities: HardwareCapabilities,
    *,
    performance_mode: str = "auto",
    backend: str = "auto",
    device: str = "auto",
    compute_type: str = "auto",
    model_name: str = "auto",
    whisper_cpp_model: str = "",
    whisper_cpp_acceleration: str = "auto",
) -> InferencePlan:
    mode = performance_mode if performance_mode in {
        "auto", "precision", "balanced", "low_power"
    } else "auto"
    cpu_threads = max(1, capabilities.physical_cores)
    if mode == "low_power":
        cpu_threads = min(2, cpu_threads)
    elif mode in {"auto", "balanced"}:
        cpu_threads = min(4, max(2, cpu_threads // 2))

    cpp_ready = bool(
        capabilities.whisper_cpp_executable
        and whisper_cpp_model
        and Path(whisper_cpp_model).expanduser().is_file()
    )
    cpp_vulkan = whisper_cpp_acceleration == "vulkan" or (
        whisper_cpp_acceleration == "auto"
        and "vulkan" in capabilities.whisper_cpp_executable.casefold()
    )
    if backend == "whisper_cpp" and cpp_ready:
        selected_backend = "whisper_cpp"
        selected_device = (
            "vulkan" if device != "cpu" and mode != "low_power"
            and capabilities.gpus and cpp_vulkan else "cpu"
        )
        reason = "Se seleccionó el componente whisper.cpp configurado."
    elif backend == "whisper_cpp":
        selected_backend = "faster_whisper"
        selected_device = "cpu"
        reason = "whisper.cpp no está completo; se usará el respaldo CPU."
    elif mode == "low_power" or device == "cpu":
        selected_backend = "faster_whisper"
        selected_device = "cpu"
        reason = "El modo de bajo consumo prioriza el procesador y limita los hilos."
    elif capabilities.cuda_available and device in {"auto", "cuda"}:
        selected_backend = "faster_whisper"
        selected_device = "cuda"
        reason = "CUDA está disponible y es el motor local más rápido detectado."
    elif (
        backend == "auto"
        and capabilities.has_cross_vendor_gpu
        and cpp_ready
        and cpp_vulkan
    ):
        selected_backend = "whisper_cpp"
        selected_device = "vulkan"
        reason = "Se detectó una GPU AMD/Intel y un componente Vulkan válido."
    elif backend == "auto" and cpp_ready and not capabilities.cuda_available:
        selected_backend = "whisper_cpp"
        selected_device = "cpu"
        reason = "Se detectó un componente whisper.cpp válido para CPU."
    else:
        selected_backend = "faster_whisper"
        selected_device = "cpu"
        reason = "No hay un acelerador compatible instalado; se usará CPU local."

    if selected_backend == "whisper_cpp":
        return InferencePlan(
            backend=selected_backend,
            device=selected_device,
            compute_type="q5_or_q8",
            model_candidates=(whisper_cpp_model,),
            cpu_threads=cpu_threads,
            performance_mode=mode,
            reason=reason,
            whisper_cpp_executable=capabilities.whisper_cpp_executable,
            whisper_cpp_model=str(Path(whisper_cpp_model).expanduser().resolve()),
        )

    if model_name and model_name != "auto":
        models = (model_name,)
    elif selected_device == "cuda" and capabilities.nvidia_vram_mb >= 6_000:
        models = ("large-v3-turbo", "small", "base")
    elif selected_device == "cuda":
        models = ("small", "base", "tiny")
    elif mode == "precision" and capabilities.memory_gb >= 16:
        models = ("small", "base", "tiny")
    elif mode == "low_power" or capabilities.physical_cores <= 4:
        models = ("tiny", "base", "small")
    else:
        models = ("base", "small", "tiny")

    if compute_type != "auto":
        selected_compute = compute_type
    elif selected_device == "cuda":
        selected_compute = (
            "float16"
            if "float16" in capabilities.cuda_compute_types
            and capabilities.nvidia_vram_mb >= 6_000
            else "int8_float16"
        )
    else:
        selected_compute = "int8"
    return InferencePlan(
        backend=selected_backend,
        device=selected_device,
        compute_type=selected_compute,
        model_candidates=models,
        cpu_threads=cpu_threads,
        performance_mode=mode,
        reason=reason,
    )


def hardware_summary(capabilities: HardwareCapabilities, plan: InferencePlan) -> str:
    gpu_names = ", ".join(gpu.name for gpu in capabilities.gpus) or "sin GPU identificada"
    summary = (
        f"{capabilities.physical_cores} núcleos físicos, {capabilities.memory_gb:.1f} GB RAM; "
        f"{gpu_names}. Configuración disponible: {plan.backend} / {plan.device} / "
        f"{plan.compute_type}. {plan.reason}"
    )
    if capabilities.cuda_setup_recommended:
        summary += (
            " Configuración ideal detectada: NVIDIA CUDA + "
            f"{capabilities.preferred_cuda_model}. Prepara el componente CUDA opcional "
            "desde este asistente para habilitarla."
        )
    return summary
