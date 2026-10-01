from __future__ import annotations

from collections import deque
from threading import Condition, Event, Thread
from typing import Callable
from time import monotonic

from auralwarden.audio import PcmChunk, PcmFormat


class CaptureQueue:
    """Drain live PCM independently of inference, with an explicit RAM limit."""

    def __init__(self, source, stop_event: Event, pcm_format: PcmFormat,
                 capacity_seconds: float = 120.0,
                 on_capture: Callable[[bytes], None] | None = None) -> None:
        self.source = source
        self.stop_event = stop_event
        self.format = pcm_format
        self.capacity = self.format.bytes_for_seconds(capacity_seconds)
        self.on_capture = on_capture
        self._items: deque[PcmChunk] = deque()
        self._bytes = 0
        self._condition = Condition()
        self._done = False
        self._error: Exception | None = None
        self.dropped_seconds = 0.0
        self.origin_monotonic: float | None = None
        self.thread = Thread(target=self._read, name="AuralWardenCapture", daemon=True)

    @property
    def queued_seconds(self) -> float:
        with self._condition:
            return self.format.seconds_for_bytes(self._bytes)

    def _read(self) -> None:
        try:
            for chunk in self.source.chunks(self.stop_event):
                if self.origin_monotonic is None:
                    self.origin_monotonic = monotonic() - chunk.end_seconds
                if self.on_capture is not None:
                    self.on_capture(chunk.data)
                with self._condition:
                    if len(chunk.data) > self.capacity:
                        removed = len(chunk.data) - self.capacity
                        duration = self.format.seconds_for_bytes(removed)
                        self.dropped_seconds += duration
                        chunk = PcmChunk(chunk.data[removed:], chunk.start_seconds + duration,
                                         chunk.end_seconds)
                    while self._items and self._bytes + len(chunk.data) > self.capacity:
                        removed_chunk = self._items.popleft()
                        self._bytes -= len(removed_chunk.data)
                        self.dropped_seconds += self.format.seconds_for_bytes(len(removed_chunk.data))
                    self._items.append(chunk)
                    self._bytes += len(chunk.data)
                    self._condition.notify_all()
        except Exception as exc:
            self._error = exc
        finally:
            with self._condition:
                self._done = True
                self._condition.notify_all()

    def chunks(self):
        self.thread.start()
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._items or self._done)
                if not self._items:
                    break
                chunk = self._items.popleft()
                self._bytes -= len(chunk.data)
            yield chunk
        self.thread.join()
        if self._error is not None:
            raise self._error
