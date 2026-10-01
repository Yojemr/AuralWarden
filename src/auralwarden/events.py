from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import RLock

from auralwarden.models import EngineEvent


EventCallback = Callable[[EngineEvent], None]


class EventBus:
    """Thread-safe event bridge between the backend and future frontends."""

    def __init__(self, max_queue_size: int = 2_000) -> None:
        self._subscribers: list[EventCallback] = []
        self._queue: Queue[EngineEvent] = Queue(maxsize=max(1, max_queue_size))
        self._lock = RLock()

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: EngineEvent) -> None:
        with self._lock:
            try:
                self._queue.put_nowait(event)
            except Full:
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
                self._queue.put_nowait(event)
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                continue

    def get(self, timeout: float | None = None) -> EngineEvent:
        return self._queue.get(timeout=timeout)

    def drain(self) -> list[EngineEvent]:
        events: list[EngineEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except Empty:
                return events
