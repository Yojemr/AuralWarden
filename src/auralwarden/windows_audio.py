from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, RLock
from typing import Any, Protocol

from auralwarden.audio import PcmChunk, PcmFormat


class WindowsAudioError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WindowsAudioDevice:
    name: str
    kind: str
    is_default: bool = False


def _pyaudio_module():
    if os.name != "nt":
        raise WindowsAudioError("La captura de audio del sistema solo está disponible en Windows.")
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise WindowsAudioError(
            "El componente portable de captura WASAPI no está disponible."
        ) from exc
    return pyaudio


def list_windows_audio_devices(kind: str) -> list[WindowsAudioDevice]:
    if kind not in {"system_audio", "microphone"}:
        return []
    pyaudio = _pyaudio_module()
    manager = pyaudio.PyAudio()
    try:
        wasapi = manager.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_index = int(
            wasapi["defaultOutputDevice"]
            if kind == "system_audio"
            else wasapi["defaultInputDevice"]
        )
        default_name = ""
        if default_index >= 0:
            default_name = str(manager.get_device_info_by_index(default_index).get("name") or "")
        devices: list[WindowsAudioDevice] = []
        for raw in manager.get_device_info_generator():
            if int(raw.get("hostApi", -1)) != int(wasapi["index"]):
                continue
            is_loopback = bool(raw.get("isLoopbackDevice"))
            if kind == "system_audio" and not is_loopback:
                continue
            if kind == "microphone" and (
                is_loopback or int(raw.get("maxInputChannels", 0)) <= 0
            ):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            comparable = name.removesuffix(" [Loopback]")
            devices.append(
                WindowsAudioDevice(
                    name=name,
                    kind=kind,
                    is_default=(comparable == default_name),
                )
            )
        return sorted(devices, key=lambda item: (not item.is_default, item.name.casefold()))
    except OSError as exc:
        raise WindowsAudioError(f"Windows no expuso dispositivos WASAPI: {exc}") from exc
    finally:
        manager.terminate()


def _downmix_and_resample(
    raw: bytes,
    channels: int,
    source_rate: int,
    target_rate: int,
) -> bytes:
    try:
        import numpy as np
    except ImportError as exc:
        raise WindowsAudioError("NumPy no está disponible para convertir el audio.") from exc
    if not raw:
        return b""
    samples = np.frombuffer(raw, dtype=np.int16)
    usable = samples.size - (samples.size % max(1, channels))
    if usable <= 0:
        return b""
    matrix = samples[:usable].reshape(-1, max(1, channels)).astype(np.float32)
    mono = matrix.mean(axis=1)
    if source_rate != target_rate and mono.size > 1:
        target_count = max(1, round(mono.size * target_rate / source_rate))
        source_positions = np.arange(mono.size, dtype=np.float64)
        target_positions = np.linspace(0, mono.size - 1, target_count, dtype=np.float64)
        mono = np.interp(target_positions, source_positions, mono)
    return np.clip(np.rint(mono), -32768, 32767).astype(np.int16).tobytes()


def _pcm_level(data: bytes) -> float:
    if not data:
        return 0.0
    try:
        import numpy as np
    except ImportError:
        return 0.0
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return min(1.0, math.sqrt(float(np.mean(samples * samples)))) if samples.size else 0.0


class WasapiPcmCapture:
    """Captures a microphone or Windows render mix and yields 16 kHz mono PCM."""

    def __init__(
        self,
        kind: str,
        device_name: str = "",
        *,
        chunk_seconds: float = 1.0,
        pcm_format: PcmFormat | None = None,
    ) -> None:
        if kind not in {"system_audio", "microphone"}:
            raise ValueError("kind must be system_audio or microphone")
        self.kind = kind
        self.device_name = device_name
        self.chunk_seconds = max(0.1, min(5.0, chunk_seconds))
        self.pcm_format = pcm_format or PcmFormat()
        self._manager: Any = None
        self._stream: Any = None
        self._lock = RLock()
        self._status_callback: Any = None

    def set_status_callback(self, callback) -> None:
        self._status_callback = callback

    def _emit(self, phase: str, **payload: object) -> None:
        if self._status_callback is not None:
            self._status_callback(phase, payload)

    def chunks(self, stop_event: Event):
        pyaudio = _pyaudio_module()
        manager = pyaudio.PyAudio()
        with self._lock:
            self._manager = manager
        try:
            raw_device = None
            stream = None
            errors: list[str] = []
            for candidate in self._resolve_devices(manager, pyaudio):
                channels = max(1, int(candidate.get("maxInputChannels", 1)))
                source_rate = max(
                    8_000, int(float(candidate.get("defaultSampleRate", 48_000)))
                )
                frames_per_chunk = max(256, round(source_rate * self.chunk_seconds))
                try:
                    stream = manager.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=source_rate,
                        input=True,
                        input_device_index=int(candidate["index"]),
                        frames_per_buffer=min(frames_per_chunk, 4096),
                    )
                    raw_device = candidate
                    break
                except OSError as exc:
                    errors.append(f"{candidate.get('name')}: {exc}")
            if stream is None or raw_device is None:
                detail = errors[-1] if errors else "ninguna interfaz aceptó el dispositivo"
                raise WindowsAudioError(
                    "Windows no permitió abrir el dispositivo de audio. Comprueba que esté "
                    "conectado, que el acceso al micrófono esté permitido y que otra aplicación "
                    f"no lo esté usando en modo exclusivo. Detalle: {detail}"
                )
            with self._lock:
                self._stream = stream
            self._emit(
                "connected",
                message=f"Capturando {raw_device.get('name', self.device_name)}.",
                device_name=str(raw_device.get("name") or ""),
            )
            elapsed = 0.0
            last_level = 0.0
            pending = bytearray()
            output_bytes = self.pcm_format.bytes_for_seconds(self.chunk_seconds)
            next_deadline = time.monotonic() + self.chunk_seconds
            while not stop_event.is_set():
                try:
                    available = int(stream.get_read_available())
                except (OSError, ValueError):
                    if stop_event.is_set():
                        break
                    raise
                if available > 0:
                    frames = min(available, frames_per_chunk)
                    try:
                        raw = stream.read(frames, exception_on_overflow=False)
                    except (OSError, ValueError) as exc:
                        if stop_event.is_set():
                            break
                        raise WindowsAudioError(f"La captura WASAPI se interrumpió: {exc}") from exc
                    pending.extend(
                        _downmix_and_resample(
                            raw,
                            channels,
                            source_rate,
                            self.pcm_format.sample_rate,
                        )
                    )
                now = time.monotonic()
                if len(pending) < output_bytes and now < next_deadline:
                    if now - last_level >= 0.5:
                        self._emit("audio_level", level=_pcm_level(bytes(pending)))
                        last_level = now
                    stop_event.wait(0.03)
                    continue
                if len(pending) < output_bytes:
                    pending.extend(b"\0" * (output_bytes - len(pending)))
                data = bytes(pending[:output_bytes])
                del pending[:output_bytes]
                duration = self.pcm_format.seconds_for_bytes(len(data))
                self._emit("audio_level", level=_pcm_level(data))
                last_level = now
                yield PcmChunk(data, elapsed, elapsed + duration)
                elapsed += duration
                next_deadline = max(next_deadline + self.chunk_seconds, now)
        finally:
            self.stop()

    def _resolve_devices(self, manager, pyaudio) -> list[dict[str, Any]]:
        try:
            wasapi = manager.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:
            raise WindowsAudioError("WASAPI no está disponible en este equipo.") from exc
        candidates: list[dict[str, Any]] = []
        for device in manager.get_device_info_generator():
            loopback = bool(device.get("isLoopbackDevice"))
            if (
                self.kind == "system_audio"
                and int(device.get("hostApi", -1)) == int(wasapi["index"])
                and loopback
            ):
                candidates.append(device)
            elif self.kind == "microphone" and not loopback and int(
                device.get("maxInputChannels", 0)
            ) > 0:
                candidates.append(device)
        if self.device_name:
            requested = self.device_name.casefold()
            exact = [device for device in candidates
                     if str(device.get("name") or "").casefold() == requested]
            matches = []
            for device in candidates:
                name = str(device.get("name") or "").casefold()
                if name == requested or (
                    min(len(name), len(requested)) >= 12
                    and (name in requested or requested in name)
                ):
                    matches.append(device)
            matches = exact or matches
            if len({str(device.get("name") or "").casefold() for device in matches}) > 1:
                raise WindowsAudioError("El nombre del dispositivo es ambiguo. Selecciona su nombre completo.")
            if matches:
                return sorted(
                    matches,
                    key=lambda item: (
                        int(item.get("hostApi", -1)) != int(wasapi["index"]),
                        -int(item.get("hostApi", -1)),
                    ),
                )
            raise WindowsAudioError(
                f"El dispositivo seleccionado '{self.device_name}' ya no está disponible. "
                "Selecciona otro dispositivo antes de iniciar la captura."
            )
        default_index = int(
            wasapi["defaultOutputDevice"]
            if self.kind == "system_audio"
            else wasapi["defaultInputDevice"]
        )
        if self.kind == "microphone":
            default_device = manager.get_default_input_device_info()
            default_name = str(default_device.get("name") or "").casefold()
            matches = [
                device
                for device in candidates
                if str(device.get("name") or "").casefold() == default_name
                or int(device.get("index", -1)) == int(default_device.get("index", -2))
            ]
            if matches:
                return matches
        else:
            output_name = ""
            if default_index >= 0:
                output_name = str(
                    manager.get_device_info_by_index(default_index).get("name") or ""
                )
            for device in candidates:
                if str(device.get("name") or "").removesuffix(" [Loopback]") == output_name:
                    return [device]
        if candidates:
            return [candidates[0]]
        label = "salida loopback" if self.kind == "system_audio" else "micrófono"
        raise WindowsAudioError(f"No se encontró ningún dispositivo de {label} compatible.")

    def stop(self) -> None:
        with self._lock:
            stream, manager = self._stream, self._manager
            self._stream = None
            self._manager = None
        if stream is not None:
            try:
                stream.stop_stream()
            except (OSError, ValueError):
                pass
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        if manager is not None:
            try:
                manager.terminate()
            except (OSError, ValueError):
                pass


@dataclass(frozen=True, slots=True)
class EndpointState:
    device_id: str
    device_name: str
    muted: bool
    volume: float


class EndpointBackend(Protocol):
    def snapshot(self, device_name: str = "") -> EndpointState: ...

    def apply(self, state: EndpointState) -> None: ...


class PycawEndpointBackend:
    @staticmethod
    def _output_name(device_name: str) -> str:
        return device_name.removesuffix(" [Loopback]").strip()

    def _find(self, device_name: str = "", device_id: str = ""):
        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            raise WindowsAudioError("El controlador local de volumen no está disponible.") from exc
        if device_id:
            for device in AudioUtilities.GetAllDevices():
                if str(device.id) == device_id:
                    return device
            raise WindowsAudioError("Windows ya no encuentra el dispositivo de audio guardado.")
        target = self._output_name(device_name).casefold()
        if not target:
            return AudioUtilities.GetSpeakers()
        outputs = [
            device
            for device in AudioUtilities.GetAllDevices()
            if str(device.id).startswith("{0.0.0.")
        ]
        for device in outputs:
            if str(device.FriendlyName).strip().casefold() == target:
                return device
        raise WindowsAudioError(f"No se encontró la salida '{self._output_name(device_name)}'.")

    def snapshot(self, device_name: str = "") -> EndpointState:
        device = self._find(device_name)
        endpoint = device.EndpointVolume
        return EndpointState(
            device_id=str(device.id),
            device_name=str(device.FriendlyName),
            muted=bool(endpoint.GetMute()),
            volume=float(endpoint.GetMasterVolumeLevelScalar()),
        )

    def apply(self, state: EndpointState) -> None:
        device = self._find(device_id=state.device_id)
        endpoint = device.EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(max(0.0, min(1.0, state.volume)), None)
        endpoint.SetMute(bool(state.muted), None)


class SilentMonitoringManager:
    """Mutes an endpoint reversibly and survives an interrupted app session."""

    def __init__(self, state_path: Path, backend: EndpointBackend | None = None) -> None:
        self.state_path = state_path
        self.backend = backend or PycawEndpointBackend()
        self._original: EndpointState | None = None

    @property
    def active(self) -> bool:
        return self._original is not None

    @property
    def device_name(self) -> str:
        return self._original.device_name if self._original is not None else ""

    def activate(self, device_name: str = "") -> EndpointState:
        if self._original is not None:
            return self._original
        original = self.backend.snapshot(device_name)
        self._write(original)
        try:
            self.backend.apply(
                EndpointState(
                    original.device_id,
                    original.device_name,
                    True,
                    original.volume,
                )
            )
        except Exception:
            self._clear_file()
            raise
        self._original = original
        return original

    def restore_original(self) -> bool:
        original = self._original or self._read()
        if original is None:
            return False
        self._original = original
        self.backend.apply(original)
        self._original = None
        self._clear_file()
        return True

    def reveal_for_alert(self, minimum_volume: float = 0.25) -> bool:
        original = self._original or self._read()
        if original is None:
            return False
        audible = EndpointState(
            original.device_id,
            original.device_name,
            False,
            max(minimum_volume, original.volume),
        )
        self.backend.apply(audible)
        self._original = None
        self._clear_file()
        return True

    def recover_interrupted(self) -> bool:
        if not self.state_path.is_file():
            return False
        return self.restore_original()

    def abandon_if_unmuted(self) -> bool:
        original = self._original
        if original is None:
            return False
        current = self.backend.snapshot(original.device_name)
        if current.muted:
            return False
        self._original = None
        self._clear_file()
        return True

    def _write(self, state: EndpointState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.state_path)

    def _read(self) -> EndpointState | None:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return EndpointState(
                device_id=str(raw["device_id"]),
                device_name=str(raw["device_name"]),
                muted=bool(raw["muted"]),
                volume=float(raw["volume"]),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _clear_file(self) -> None:
        try:
            self.state_path.unlink(missing_ok=True)
        except OSError:
            pass
