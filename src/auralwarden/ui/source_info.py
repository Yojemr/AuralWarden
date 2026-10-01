from __future__ import annotations

from threading import Thread

from PySide6.QtCore import QObject, Signal

from auralwarden.source_info import SourceInfo, resolve_source_info


class SourceInfoSession(QObject):
    ready = Signal(str, object)

    def request(self, source: str) -> None:
        value = source.strip()

        def resolve() -> None:
            info: SourceInfo = resolve_source_info(value)
            try:
                self.ready.emit(value, info)
            except RuntimeError:
                return

        Thread(
            target=resolve,
            name="AuralWardenSourceInfo",
            daemon=True,
        ).start()
