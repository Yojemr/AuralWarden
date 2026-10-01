from __future__ import annotations

import math
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(frozen=True, slots=True)
class PcmFormat:
    sample_rate: int = 16_000
    channels: int = 1
    sample_width: int = 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * self.sample_width

    def seconds_for_bytes(self, byte_count: int) -> float:
        return byte_count / self.bytes_per_second

    def bytes_for_seconds(self, seconds: float) -> int:
        frame_size = self.channels * self.sample_width
        raw = max(0, int(seconds * self.bytes_per_second))
        return raw - (raw % frame_size)


@dataclass(frozen=True, slots=True)
class PcmChunk:
    data: bytes
    start_seconds: float
    end_seconds: float


def write_pcm_wav(path: Path, data: bytes, pcm_format: PcmFormat) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(pcm_format.channels)
        output.setsampwidth(pcm_format.sample_width)
        output.setframerate(pcm_format.sample_rate)
        output.writeframes(data)


class PcmRingBuffer:
    """Exact-size in-memory circular buffer for raw PCM audio."""

    def __init__(self, capacity_seconds: float, pcm_format: PcmFormat | None = None) -> None:
        if capacity_seconds <= 0:
            raise ValueError("capacity_seconds must be positive")
        self.format = pcm_format or PcmFormat()
        self.capacity_seconds = float(capacity_seconds)
        self._capacity_bytes = self.format.bytes_for_seconds(capacity_seconds)
        self._data = bytearray()
        self._lock = RLock()

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            return self.format.seconds_for_bytes(len(self._data))

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            if len(data) >= self._capacity_bytes:
                self._data = bytearray(data[-self._capacity_bytes :])
                return
            self._data.extend(data)
            overflow = len(self._data) - self._capacity_bytes
            if overflow > 0:
                del self._data[:overflow]

    def tail(self, seconds: float) -> bytes:
        requested = self.format.bytes_for_seconds(seconds)
        with self._lock:
            if requested <= 0:
                return b""
            return bytes(self._data[-requested:])

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._data)

    def interval(self, start_seconds: float, end_seconds: float,
                 captured_until_seconds: float) -> tuple[bytes, bool]:
        with self._lock:
            available_start = captured_until_seconds - self.format.seconds_for_bytes(len(self._data))
            start = max(start_seconds, available_start)
            end = min(end_seconds, captured_until_seconds)
            if end <= start:
                return b"", end_seconds > start_seconds
            first = self.format.bytes_for_seconds(start - available_start)
            last = self.format.bytes_for_seconds(end - available_start)
            return bytes(self._data[first:last]), start > start_seconds + 0.001

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def pcm_rms(data: bytes, pcm_format: PcmFormat) -> float:
    """Return normalized RMS amplitude for signed 16-bit PCM."""

    if not data:
        return 0.0
    if pcm_format.sample_width != 2:
        raise ValueError("pcm_rms solo admite PCM de 16 bits.")
    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return min(1.0, math.sqrt(mean_square) / 32768.0)


class WaveRecorder:
    def __init__(self, path: Path, pcm_format: PcmFormat) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._wave = wave.open(str(path), "wb")
        self._wave.setnchannels(pcm_format.channels)
        self._wave.setsampwidth(pcm_format.sample_width)
        self._wave.setframerate(pcm_format.sample_rate)
        self._closed = False

    def write(self, data: bytes) -> None:
        if not self._closed and data:
            self._wave.writeframesraw(data)

    def close(self) -> None:
        if not self._closed:
            self._wave.close()
            self._closed = True

    def __enter__(self) -> "WaveRecorder":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
