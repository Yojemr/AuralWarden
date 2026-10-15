from __future__ import annotations

import ctypes
import multiprocessing
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from typing import Callable

from auralwarden.audio import PcmChunk
from auralwarden.windows_audio import WasapiPcmCapture


class WindowCaptureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WindowTarget:
    hwnd: int
    pid: int
    created_at: float
    title: str
    executable: str


def _user32():
    if os.name != "nt":
        raise WindowCaptureError("La captura de ventanas solo está disponible en Windows.")
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.IsWindow.argtypes = [wintypes.HWND]
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsIconic.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    return api


def window_target(hwnd: int) -> WindowTarget:
    import psutil

    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0:
        raise WindowCaptureError("Selecciona una ventana válida.")
    api = _user32()
    if not api.IsWindow(hwnd) or not api.IsWindowVisible(hwnd):
        raise WindowCaptureError("La ventana seleccionada ya no está disponible.")
    pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        process = psutil.Process(pid.value)
        executable = process.exe()
        created_at = process.create_time()
    except (psutil.Error, OSError) as exc:
        raise WindowCaptureError("No se pudo identificar la ventana seleccionada.") from exc
    title_buffer = ctypes.create_unicode_buffer(api.GetWindowTextLengthW(hwnd) + 1)
    api.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    return WindowTarget(hwnd, pid.value, created_at, title_buffer.value, executable)


def validate_target(target: WindowTarget) -> None:
    current = window_target(target.hwnd)
    if (current.pid != target.pid or current.created_at != target.created_at
            or current.executable.casefold() != target.executable.casefold()):
        raise WindowCaptureError("La ventana original se cerró; no se capturará otra en su lugar.")
    if _user32().IsIconic(target.hwnd):
        raise WindowCaptureError("La ventana está minimizada. Restáurala para grabar su vídeo.")


def list_capture_windows() -> list[WindowTarget]:
    api = _user32()
    targets: list[WindowTarget] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        if api.IsWindowVisible(hwnd) and api.GetWindowTextLengthW(hwnd) > 0:
            try:
                target = window_target(int(hwnd))
                if target.pid != os.getpid():
                    targets.append(target)
            except WindowCaptureError:
                pass
        return True

    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows(visit, 0)
    return sorted(targets, key=lambda item: item.title.casefold())


def output_dimensions(width: int, height: int, max_width: int = 1280) -> tuple[int, int]:
    if width < 2 or height < 2 or width * height > 16_777_216:
        raise WindowCaptureError("El tamaño de la ventana no es compatible con la captura.")
    ratio = min(1.0, max_width / width, 720 / height)
    return max(2, int(width * ratio) // 2 * 2), max(2, int(height * ratio) // 2 * 2)


def _capture_window_frames(target, pixels, metadata, lock, ready, stop, errors):
    """The native backend owns no files; its lifetime is bounded by the parent."""
    import av
    import numpy as np
    import psutil
    from windows_capture import WindowsCapture

    owner = psutil.Process(os.getppid())
    try:
        validate_target(target)
        capture = WindowsCapture(window_hwnd=target.hwnd, monitor_index=None,
                                 cursor_capture=None, draw_border=None,
                                 secondary_window=None, minimum_update_interval=None)
        previous = 0.0

        @capture.event
        def on_frame_arrived(frame, control):
            nonlocal previous
            if stop.is_set() or time.monotonic() - previous < 1 / 15:
                return
            try:
                width, height = output_dimensions(frame.width, frame.height)
                converted = av.VideoFrame.from_ndarray(frame.frame_buffer, format="bgra")
                image = converted.reformat(width=width, height=height).to_ndarray(format="bgra")
                if lock.acquire(timeout=0.02):
                    try:
                        view = np.frombuffer(pixels, dtype=np.uint8)
                        view[:image.size] = image.reshape(-1)
                        metadata[0], metadata[1] = width, height
                        metadata[2] += 1
                    finally:
                        lock.release()
                    ready.set()
                    previous = time.monotonic()
            except Exception as exc:
                try:
                    errors.put_nowait(str(exc))
                except Full:
                    pass
                ready.set()

        @capture.event
        def on_closed():
            if not stop.is_set():
                try:
                    errors.put_nowait("La ventana original se cerró; no se cambiará de fuente.")
                except Full:
                    pass
                ready.set()

        control = capture.start_free_threaded()
        while not stop.wait(0.25):
            if not owner.is_running():
                os._exit(0)
        # Windows 10/native backend shutdown can wait for a callback holding
        # the GIL. This child has no persistent state; the parent ends it.
        os._exit(0)
    except BaseException as exc:
        try:
            errors.put(str(exc), timeout=0.2)
        except Full:
            pass
        ready.set()


class WindowVideoRecorder:
    """WGC captures only the chosen HWND; one encoder owns all media state."""

    def __init__(self, target: WindowTarget, directory: Path, *, fps: int = 15,
                 segment_seconds: float = 2.0, frame_factory=None) -> None:
        self.target = target
        self.directory = directory
        self.fps = max(5, min(30, int(fps)))
        self.segment_seconds = max(1.0, min(10.0, segment_seconds))
        self.manifest_path = directory / "segments.csv"
        self._factory = frame_factory
        self._frame = None
        self._lock = RLock()
        self._first_frame = Event()
        self._begin = Event()
        self._stop = Event()
        self._audio: Queue[PcmChunk] = Queue(maxsize=32)
        self._capture = None
        self._control = None
        self._thread: Thread | None = None
        self.error = ""
        self.frames_written = 0
        self.audio_seconds = 0.0
        self._origin = 0.0
        self._last_frame_time = 0.0
        self._native_process = None
        self._native_stop = None
        self._native_errors = None
        self._native_pixels = None
        self._native_metadata = None
        self._native_lock = None
        self._native_counter = 0

    def start(self) -> None:
        import numpy as np

        validate_target(self.target)
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._factory is None:
            context = multiprocessing.get_context("spawn")
            self._native_pixels = context.Array("B", 1280 * 720 * 4, lock=False)
            self._native_metadata = context.Array("i", 3, lock=False)
            self._native_lock = context.Lock()
            ready = context.Event()
            self._native_stop = context.Event()
            self._native_errors = context.Queue(maxsize=4)
            self._native_process = context.Process(
                target=_capture_window_frames,
                args=(self.target, self._native_pixels, self._native_metadata,
                      self._native_lock, ready, self._native_stop, self._native_errors),
                name="AuralWardenWindowFrames", daemon=True,
            )
            self._native_process.start()
            if not ready.wait(8.0):
                self.stop()
                raise WindowCaptureError("Windows no entregó imágenes de la ventana a tiempo.")
            self._poll_native_error()
            self._read_native_frame()
            if self.error or self._frame is None:
                self.stop()
                raise WindowCaptureError(self.error or "La ventana no entregó un cuadro válido.")
            self._thread = Thread(target=self._encode, name="AuralWardenWindowVideo", daemon=True)
            self._thread.start()
            return
        self._capture = self._factory(window_hwnd=self.target.hwnd, monitor_index=None,
                                      cursor_capture=None, draw_border=None,
                                      secondary_window=None, minimum_update_interval=None)

        @self._capture.event
        def on_frame_arrived(frame, control):
            if self._stop.is_set():
                control.stop()
                return
            try:
                now = time.monotonic()
                if self._frame is not None and now - self._last_frame_time < 1 / self.fps:
                    return
                output_dimensions(frame.width, frame.height)
                pixels = np.array(frame.frame_buffer, dtype=np.uint8, copy=True, order="C")
                if pixels.shape != (frame.height, frame.width, 4):
                    raise WindowCaptureError("Windows entregó un cuadro de vídeo inválido.")
                with self._lock:
                    self._frame = pixels
                    self._last_frame_time = now
                self._first_frame.set()
            except Exception as exc:
                self.error = str(exc)
                self._first_frame.set()
                control.stop()

        @self._capture.event
        def on_closed():
            if not self._stop.is_set():
                self.error = "La ventana capturada se cerró; el vídeo se finalizará sin cambiar de fuente."
                self._first_frame.set()

        self._control = self._capture.start_free_threaded()
        if not self._first_frame.wait(8.0) or self._frame is None or self.error:
            self.stop()
            raise WindowCaptureError(self.error or "Windows no entregó imágenes de la ventana.")
        self._thread = Thread(target=self._encode, name="AuralWardenWindowVideo", daemon=True)
        self._thread.start()

    def _poll_native_error(self) -> None:
        if self._native_errors is not None:
            try:
                self.error = self.error or self._native_errors.get_nowait()
            except Empty:
                pass
        if (self._native_process is not None and not self._stop.is_set()
                and not self._native_process.is_alive()):
            self.error = self.error or "El componente de captura de ventanas se interrumpió."

    def _read_native_frame(self) -> None:
        if self._native_pixels is None:
            return
        import numpy as np

        if not self._native_lock.acquire(timeout=0.1):
            return
        try:
            width, height, counter = self._native_metadata
            if counter <= self._native_counter or not width or not height:
                return
            output_dimensions(width, height)
            image = np.frombuffer(self._native_pixels, dtype=np.uint8, count=width * height * 4)
            with self._lock:
                self._frame = image.reshape(height, width, 4).copy()
                self._native_counter = counter
        finally:
            self._native_lock.release()

    def begin(self) -> None:
        if not self._begin.is_set():
            self._origin = time.monotonic()
            self._begin.set()

    def feed_audio(self, chunk: PcmChunk) -> None:
        self._poll_native_error()
        if self.error:
            raise WindowCaptureError(self.error)
        try:
            self._audio.put_nowait(chunk)
        except Full as exc:
            self.error = "El codificador de vídeo no mantiene el ritmo; el búfer de audio está lleno."
            raise WindowCaptureError(self.error) from exc

    def _encode(self) -> None:
        import av
        import numpy as np

        container = None
        try:
            while not self._begin.wait(0.05):
                if self._stop.is_set():
                    return
            with self._lock:
                pixels = self._frame
            height, width = pixels.shape[:2]
            width, height = output_dimensions(width, height)
            container = av.open(str(self.directory / "segment-%06d.ts"), mode="w", format="segment",
                                options={"segment_time": str(self.segment_seconds),
                                         "segment_list": str(self.manifest_path),
                                         "segment_list_type": "csv", "segment_list_size": "0",
                                         "reset_timestamps": "1"})
            video = container.add_stream("libx264", rate=self.fps)
            video.width, video.height, video.pix_fmt = width, height, "yuv420p"
            video.codec_context.thread_count = 2
            video.options = {"preset": "veryfast", "tune": "zerolatency", "crf": "25",
                             "g": str(round(self.fps * self.segment_seconds)),
                             "sc_threshold": "0", "bf": "0"}
            audio = container.add_stream("aac", rate=16_000)
            audio.layout = "mono"
            audio.bit_rate = 64_000
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16_000)
            next_video = 0
            next_check = 0.0
            while not self._stop.is_set() or not self._audio.empty():
                for _ in range(4):
                    try:
                        chunk = self._audio.get_nowait()
                    except Empty:
                        break
                    samples = np.frombuffer(chunk.data, dtype=np.int16).reshape(1, -1)
                    frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
                    frame.sample_rate = 16_000
                    frame.time_base = Fraction(1, 16_000)
                    frame.pts = round(chunk.start_seconds * 16_000)
                    for converted in resampler.resample(frame):
                        for packet in audio.encode(converted):
                            container.mux(packet)
                    self.audio_seconds = chunk.end_seconds
                now = time.monotonic()
                if not self._stop.is_set() and now >= next_check:
                    self._poll_native_error()
                    validate_target(self.target)
                    if self.error:
                        raise WindowCaptureError(self.error)
                    next_check = now + 0.5
                elapsed = max(0.0, now - self._origin)
                if next_video / self.fps <= elapsed:
                    if elapsed - next_video / self.fps > 3.0:
                        raise WindowCaptureError("La captura de vídeo se retrasó demasiado; baja la resolución o la carga del equipo.")
                    self._read_native_frame()
                    with self._lock:
                        pixels = self._frame
                    frame = av.VideoFrame.from_ndarray(pixels, format="bgra")
                    frame = frame.reformat(width=width, height=height, format="yuv420p")
                    frame.pts = next_video
                    frame.time_base = Fraction(1, self.fps)
                    for packet in video.encode(frame):
                        container.mux(packet)
                    next_video += 1
                    self.frames_written = next_video
                elif not self._stop.is_set():
                    self._stop.wait(min(0.02, max(0.0, next_video / self.fps - elapsed)))
            for frame in resampler.resample(None):
                for packet in audio.encode(frame):
                    container.mux(packet)
            for stream in (video, audio):
                for packet in stream.encode(None):
                    container.mux(packet)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception as exc:
                    self.error = self.error or str(exc)

    def stop(self) -> None:
        self._stop.set()
        if self._native_process is not None:
            self._native_stop.set()
            self._native_process.join(timeout=1.0)
            if self._native_process.is_alive():
                self._native_process.terminate()
                self._native_process.join(timeout=3.0)
            if self._native_process.is_alive():
                raise WindowCaptureError("El proceso auxiliar todavía no se ha cerrado.")
        if self._control is not None:
            control, self._control = self._control, None
            try:
                control.stop()
            except Exception as exc:
                self.error = self.error or str(exc)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=15.0)
            if thread.is_alive():
                raise WindowCaptureError("El vídeo todavía se está finalizando; sus segmentos se conservaron.")
        if self._native_errors is not None:
            self._native_errors.close()
            self._native_errors = None


class WindowPcmCapture:
    def __init__(self, target: WindowTarget, audio_device: str = "", *, fps: int = 15) -> None:
        self.target = target
        self.audio = WasapiPcmCapture("system_audio", audio_device)
        self.fps = fps
        self.video: WindowVideoRecorder | None = None
        self._directory: Path | None = None
        self._segment_seconds = 2.0
        self._status: Callable | None = None
        self.audio.set_status_callback(self._audio_status)

    def set_status_callback(self, callback) -> None:
        self._status = callback

    def _audio_status(self, phase, payload) -> None:
        if phase == "connected" and self.video is not None:
            self.video.begin()
        if self._status is not None:
            self._status(phase, payload)

    def configure_video_buffer(self, directory: Path, *, segment_seconds: float = 2.0) -> Path:
        self._directory = directory
        self._segment_seconds = segment_seconds
        return directory / "segments.csv"

    def chunks(self, stop_event: Event):
        validate_target(self.target)
        try:
            if self._directory is not None:
                self.video = WindowVideoRecorder(self.target, self._directory, fps=self.fps,
                                                 segment_seconds=self._segment_seconds)
                self.video.start()
            for chunk in self.audio.chunks(stop_event):
                if self.video is not None:
                    self.video.feed_audio(chunk)
                yield chunk
        finally:
            self.audio.stop()
            if self.video is not None:
                self.video.stop()
                if self.video.error:
                    raise WindowCaptureError(self.video.error)

    def stop(self) -> None:
        self.audio.stop()
