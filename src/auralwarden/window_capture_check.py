from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4


def run_window_capture_check(destination: Path | None) -> int:
    if destination is None:
        raise ValueError("Indica un archivo de salida para la comprobación de ventanas.")
    import av
    import numpy as np
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtWidgets import QApplication, QLabel
    from auralwarden import __version__
    from auralwarden.audio import PcmChunk
    from auralwarden.video_clips import render_full_video_recording
    from auralwarden.window_video import WindowPcmCapture, window_target

    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory = destination.parent / f"synthetic-window-check-{uuid4().hex}"
    app = QApplication.instance() or QApplication([])
    window = QLabel("AuralWarden — synthetic window capture test")
    window.setWindowTitle("AuralWarden synthetic capture target")
    window.setTextFormat(Qt.TextFormat.PlainText)
    window.setStyleSheet("background:#173f56;color:white;font-size:14px;")
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.resize(420, 240)
    window.show()
    app.processEvents()
    target = window_target(int(window.winId()))
    report = {"version": __version__, "input_audio": "synthetic", "status": "failed"}

    class SyntheticAudio:
        def set_status_callback(self, callback):
            self.callback = callback

        def chunks(self, stop):
            self.callback("connected", {})
            tone = (np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000) * 3000).astype(np.int16)
            for index in range(4):
                if stop.wait(1):
                    break
                yield PcmChunk(tone.tobytes(), index, index + 1)

        def stop(self):
            pass

    def check():
        source = WindowPcmCapture(target)
        source.audio = SyntheticAudio()
        source.audio.set_status_callback(source._audio_status)
        try:
            manifest = source.configure_video_buffer(directory)
            for chunk in source.chunks(Event()):
                report["captured_seconds"] = chunk.end_seconds
            path = render_full_video_recording(manifest, directory, directory / "synthetic-check.mp4")
            with av.open(str(path)) as media:
                report["streams"] = [stream.type for stream in media.streams]
                frame = next(media.decode(video=0))
                report["width"], report["height"] = frame.width, frame.height
            assert set(report["streams"]) == {"video", "audio"}
            assert report["captured_seconds"] == 4
            report["status"] = "ok"
        except Exception as exc:
            report["error"] = str(exc)
        finally:
            source.stop()
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)

    worker = Thread(target=check, name="AuralWardenSyntheticWindowCheck", daemon=True)
    worker.start()
    app.exec()
    worker.join(timeout=20)
    window.close()
    return 0 if report["status"] == "ok" else 1
