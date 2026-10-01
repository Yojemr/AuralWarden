from __future__ import annotations

import csv
import shutil
import subprocess
import time
from collections import deque
from enum import StrEnum

from auralwarden.models import ResourceSnapshot

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class ResourceSampler:
    def __init__(self) -> None:
        self._last_network_bytes: int | None = None
        self._last_network_time: float | None = None
        self._process = psutil.Process() if psutil is not None else None

    def sample(self) -> ResourceSnapshot:
        snapshot = ResourceSnapshot()
        if psutil is not None:
            snapshot.cpu_percent = float(psutil.cpu_percent(interval=None))
            snapshot.memory_percent = float(psutil.virtual_memory().percent)
            if self._process is not None:
                snapshot.process_memory_mb = self._process.memory_info().rss / (1024 * 1024)
            counters = psutil.net_io_counters()
            now = time.monotonic()
            total = counters.bytes_sent + counters.bytes_recv
            if self._last_network_bytes is not None and self._last_network_time is not None:
                elapsed = max(0.001, now - self._last_network_time)
                snapshot.network_mbps = max(
                    0.0, (total - self._last_network_bytes) * 8 / elapsed / 1_000_000
                )
            self._last_network_bytes = total
            self._last_network_time = now
        gpu = self._sample_nvidia()
        if gpu is not None:
            snapshot.gpu_percent, snapshot.vram_used_mb, snapshot.vram_total_mb = gpu
        return snapshot

    @staticmethod
    def _sample_nvidia() -> tuple[float, float, float] | None:
        executable = shutil.which("nvidia-smi")
        if executable is None:
            return None
        command = [
            executable,
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            row = next(csv.reader([result.stdout.strip().splitlines()[0]]))
            return float(row[0]), float(row[1]), float(row[2])
        except (OSError, ValueError, IndexError, StopIteration, subprocess.SubprocessError):
            return None


class LoadProfile(StrEnum):
    NORMAL = "normal"
    CONSTRAINED = "constrained"
    CRITICAL = "critical"


class ResourceHistory:
    def __init__(self, max_samples: int = 60) -> None:
        self._samples: deque[ResourceSnapshot] = deque(maxlen=max(1, max_samples))

    def add(self, snapshot: ResourceSnapshot) -> None:
        self._samples.append(snapshot)

    def snapshots(self) -> tuple[ResourceSnapshot, ...]:
        return tuple(self._samples)


class AdaptiveLoadController:
    def __init__(
        self,
        constrained_percent: float = 85.0,
        critical_percent: float = 95.0,
        constrained_samples: int = 2,
        critical_samples: int = 2,
        recovery_samples: int = 3,
        hysteresis_percent: float = 8.0,
    ) -> None:
        self.constrained_percent = constrained_percent
        self.critical_percent = critical_percent
        self.constrained_samples = max(1, constrained_samples)
        self.critical_samples = max(1, critical_samples)
        self.recovery_samples = max(1, recovery_samples)
        self.hysteresis_percent = max(0.0, hysteresis_percent)
        self.profile = LoadProfile.NORMAL
        self.pressure_percent = 0.0
        self.pressure_source = "cpu"
        self._constrained_streak = 0
        self._critical_streak = 0
        self._recovery_streak = 0

    def update(self, snapshot: ResourceSnapshot) -> LoadProfile:
        pressures = {
            "cpu": float(snapshot.cpu_percent),
            "gpu": float(snapshot.gpu_percent or 0.0),
            "ram": float(snapshot.memory_percent),
        }
        if snapshot.vram_used_mb is not None and snapshot.vram_total_mb:
            pressures["vram"] = (
                float(snapshot.vram_used_mb) / float(snapshot.vram_total_mb) * 100.0
            )
        self.pressure_source, self.pressure_percent = max(
            pressures.items(), key=lambda item: item[1]
        )
        utilization = self.pressure_percent

        self._critical_streak = (
            self._critical_streak + 1
            if utilization >= self.critical_percent
            else 0
        )
        self._constrained_streak = (
            self._constrained_streak + 1
            if utilization >= self.constrained_percent
            else 0
        )

        if self._critical_streak >= self.critical_samples:
            self.profile = LoadProfile.CRITICAL
            self._recovery_streak = 0
            return self.profile
        if (
            self.profile == LoadProfile.NORMAL
            and self._constrained_streak >= self.constrained_samples
        ):
            self.profile = LoadProfile.CONSTRAINED
            self._recovery_streak = 0
            return self.profile

        recovery_threshold = (
            self.critical_percent - self.hysteresis_percent
            if self.profile == LoadProfile.CRITICAL
            else self.constrained_percent - self.hysteresis_percent
        )
        if self.profile != LoadProfile.NORMAL and utilization < recovery_threshold:
            self._recovery_streak += 1
        else:
            self._recovery_streak = 0
        if self._recovery_streak >= self.recovery_samples:
            self.profile = (
                LoadProfile.CONSTRAINED
                if self.profile == LoadProfile.CRITICAL
                and utilization >= self.constrained_percent - self.hysteresis_percent
                else LoadProfile.NORMAL
            )
            self._recovery_streak = 0
        return self.profile
