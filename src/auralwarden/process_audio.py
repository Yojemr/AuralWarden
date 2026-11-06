from __future__ import annotations

import multiprocessing as mp
import os
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full
from threading import Event, RLock

import psutil

from auralwarden.audio import PcmChunk, PcmFormat
from auralwarden.windows_audio import WindowsAudioError, _pcm_level


@dataclass(frozen=True, slots=True)
class ProcessTarget:
    pid: int
    created_at: float
    executable: str

    @classmethod
    def from_window(cls, window) -> ProcessTarget:
        return cls(window.pid, window.created_at, window.executable)


def validate_process_target(target: ProcessTarget) -> None:
    if (type(target.pid) is not int or target.pid <= 0
            or target.created_at <= 0 or not target.executable):
        raise WindowsAudioError("Selecciona explícitamente una aplicación válida.")
    try:
        process = psutil.Process(target.pid)
        valid = (process.is_running() and process.create_time() == target.created_at
                 and process.exe().casefold() == target.executable.casefold())
    except (psutil.Error, OSError) as exc:
        raise WindowsAudioError("La aplicación seleccionada ya no está disponible.") from exc
    if not valid:
        raise WindowsAudioError(
            "La aplicación original se cerró o cambió; selecciona de nuevo. "
            "No se capturará otra aplicación ni el audio completo del equipo."
        )


class ProcessAudioConverter:
    """Stateful conversion avoids rounding drift between native WASAPI packets."""

    def __init__(self):
        import av

        self.av = av
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

    def convert(self, raw: bytes) -> bytes:
        if not raw or len(raw) % 4:
            raise WindowsAudioError("El audio nativo debe contener fotogramas estéreo completos.")
        frame = self.av.AudioFrame(format="s16", layout="stereo", samples=len(raw) // 4)
        frame.sample_rate = 44100
        frame.planes[0].update(raw)
        return self._bytes(self.resampler.resample(frame))

    @staticmethod
    def _bytes(frames) -> bytes:
        return b"".join(bytes(frame.planes[0])[:frame.samples * 2] for frame in frames)

    def flush(self) -> bytes:
        return self._bytes(self.resampler.resample(None))


def _capture_process_audio(target, packets, errors, stop):
    from auralwarden._process_audio_native import NativeProcessLoopback

    reader = None
    try:
        owner = psutil.Process(os.getppid())
        validate_process_target(target)
        reader = NativeProcessLoopback(target.pid, stop)
        validate_process_target(target)
        converter = ProcessAudioConverter()
        packets.put(("connected", b""), timeout=0.5)
        native_pending = bytearray()
        output_pending = bytearray()
        native_second = 44100 * 4
        deadline = time.monotonic() + 1.1
        next_check = time.monotonic()
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_check:
                if not owner.is_running():
                    return
                validate_process_target(target)
                next_check = now + 0.5
            native_pending.extend(reader.read())
            now = time.monotonic()
            if len(native_pending) > native_second * 3 or now - deadline > 3:
                raise WindowsAudioError("La captura de aplicación se retrasó; reduce la carga del equipo.")
            if len(native_pending) < native_second and now < deadline:
                continue
            if len(native_pending) < native_second:
                native_pending.extend(bytes(native_second - len(native_pending)))
            raw = bytes(native_pending[:native_second])
            del native_pending[:native_second]
            data = converter.convert(raw)
            if data:
                try:
                    packets.put(("pcm", data), timeout=0.2)
                except Full as exc:
                    raise WindowsAudioError("El búfer de aplicación se llenó; la captura se detuvo sin cambiar de fuente.") from exc
            deadline += 1.0
        if native_pending:
            output_pending.extend(converter.convert(bytes(native_pending)))
        output_pending.extend(converter.flush())
        if output_pending:
            try:
                packets.put(("pcm", bytes(output_pending)), timeout=0.2)
            except Full:
                pass
    except Exception as exc:
        try:
            errors.put(str(exc), timeout=0.2)
        except Full:
            pass
    finally:
        if reader is not None:
            reader.close()
        packets.cancel_join_thread()
        errors.cancel_join_thread()


class ProcessPcmCapture:
    """Opt-in capture of one verified process tree, with a bounded native worker."""

    def __init__(self, target: ProcessTarget):
        self.target = target
        self.pcm_format = PcmFormat()
        self._status_callback = None
        self._stop = None
        self._local_stop = Event()
        self._lock = RLock()

    def set_status_callback(self, callback):
        self._status_callback = callback

    def _emit(self, phase, **payload):
        if self._status_callback is not None:
            self._status_callback(phase, payload)

    def chunks(self, stop_event: Event):
        if os.name != "nt":
            raise WindowsAudioError("El audio por aplicación requiere Windows y la API de loopback por proceso.")
        validate_process_target(self.target)
        context = mp.get_context("spawn")
        packets, errors = context.Queue(maxsize=16), context.Queue(maxsize=1)
        worker_stop = context.Event()
        with self._lock:
            self._stop = worker_stop
        worker = context.Process(target=_capture_process_audio,
                                 args=(self.target, packets, errors, worker_stop), daemon=True)
        started = False
        connected = False
        elapsed = 0.0
        deadline = time.monotonic() + 12.0
        try:
            if stop_event.is_set() or self._local_stop.is_set():
                return
            worker.start()
            started = True
            while not stop_event.is_set() and not self._local_stop.is_set():
                try:
                    message = errors.get_nowait()
                except Empty:
                    message = ""
                if message:
                    raise WindowsAudioError(message)
                try:
                    phase, data = packets.get(timeout=0.1)
                except Empty:
                    if not worker.is_alive() or time.monotonic() >= deadline:
                        raise WindowsAudioError(
                            "La captura de aplicación se interrumpió o no respondió. "
                            "No se cambió al audio del sistema."
                        )
                    continue
                deadline = time.monotonic() + 5.0
                if phase == "connected":
                    connected = True
                    self._emit("connected", message="Capturando solo la aplicación seleccionada y sus procesos hijos.",
                               device_name=Path(self.target.executable).stem)
                elif phase == "pcm" and connected:
                    if not data or len(data) > 64000 or len(data) % 2:
                        raise WindowsAudioError("El proceso de audio entregó un búfer inválido.")
                    duration = self.pcm_format.seconds_for_bytes(len(data))
                    self._emit("audio_level", level=_pcm_level(data))
                    yield PcmChunk(data, elapsed, elapsed + duration)
                    elapsed += duration
                else:
                    raise WindowsAudioError("El proceso de audio entregó un mensaje inválido.")
        finally:
            worker_stop.set()
            if started:
                worker.join(timeout=1.0)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=2.0)
                if worker.is_alive():
                    raise WindowsAudioError("No se pudo cerrar el auxiliar de audio.")
                worker.close()
            with self._lock:
                self._stop = None
            for channel in (packets, errors):
                channel.close()
                channel.cancel_join_thread()

    def stop(self):
        self._local_stop.set()
        with self._lock:
            if self._stop is not None:
                self._stop.set()
