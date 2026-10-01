from __future__ import annotations

import subprocess
import time
from collections import deque
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal

from auralwarden.paths import runtime_executable


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PreviewWorker(QObject):
    frame_ready = Signal(bytes)
    status_changed = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        source: str,
        *,
        synced: bool,
        delay_seconds: float,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.synced = synced
        self.delay_seconds = max(0.0, delay_seconds if synced else 0.0)
        self._stop = Event()
        self._process: subprocess.Popen[bytes] | None = None

    def run(self) -> None:
        try:
            input_source, local = self._resolve_source()
            ffmpeg = runtime_executable("ffmpeg")
            if not ffmpeg:
                raise RuntimeError("FFmpeg no está disponible para la vista previa.")
            command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
            if local:
                command.append("-re")
            command.extend(
                [
                    "-i",
                    input_source,
                    "-an",
                    "-vf",
                    "fps=0.5,scale=640:-2",
                    "-q:v",
                    "5",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ]
            )
            self.status_changed.emit("Sincronizando" if self.synced else "En vivo")
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            if self._process.stdout is None:
                raise RuntimeError("FFmpeg no expuso los fotogramas de vista previa.")
            buffer = bytearray()
            delayed: deque[tuple[float, bytes]] = deque()
            while not self._stop.is_set():
                chunk = self._process.stdout.read(16 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start < 0 or end < 0:
                        if len(buffer) > 4 * 1024 * 1024:
                            del buffer[:-2]
                        break
                    frame = bytes(buffer[start : end + 2])
                    del buffer[: end + 2]
                    delayed.append((time.monotonic(), frame))
                    now = time.monotonic()
                    while delayed and now - delayed[0][0] >= self.delay_seconds:
                        _, ready = delayed.popleft()
                        self.frame_ready.emit(ready)
            if not self._stop.is_set() and self._process.poll() not in (0, None):
                raise RuntimeError("La vista previa del directo se interrumpió.")
        except Exception as exc:
            if not self._stop.is_set():
                self.error.emit(str(exc))
        finally:
            self.stop()
            self.finished.emit()

    def _resolve_source(self) -> tuple[str, bool]:
        local = Path(self.source).expanduser()
        if local.exists():
            return str(local.resolve()), True
        try:
            from streamlink import Streamlink
        except ImportError as exc:
            raise RuntimeError("Streamlink no está instalado para la vista previa.") from exc
        streams = Streamlink().streams(self.source)
        selected = streams.get("best")
        if selected is None:
            video_streams = [
                stream
                for name, stream in streams.items()
                if name not in {"audio_only", "audio"}
            ]
            selected = video_streams[-1] if video_streams else None
        if selected is None:
            raise RuntimeError("No se encontró una pista de vídeo para la vista previa.")
        to_url = getattr(selected, "to_url", None)
        if callable(to_url):
            return str(to_url()), False
        url = getattr(selected, "url", None)
        if not url:
            raise RuntimeError("Streamlink no pudo exponer la pista de vídeo.")
        return str(url), False

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._process = None


class PreviewSession(QObject):
    frame_ready = Signal(bytes)
    status_changed = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: PreviewWorker | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, source: str, *, synced: bool, delay_seconds: float) -> None:
        self.stop()
        thread = QThread(self)
        worker = PreviewWorker(
            source,
            synced=synced,
            delay_seconds=delay_seconds,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.frame_ready.connect(self.frame_ready)
        worker.status_changed.connect(self.status_changed)
        worker.error.connect(self.error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self) -> None:
        worker = self._worker
        thread = self._thread
        if worker is not None:
            worker.stop()
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3_000)
        self._worker = None
        self._thread = None

    def _clear_finished(self) -> None:
        self._worker = None
        self._thread = None
