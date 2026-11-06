from __future__ import annotations

import argparse
import json
import multiprocessing
import shutil
import sys
import time
from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from auralwarden import __version__
from auralwarden.paths import data_dir, sessions_dir
from auralwarden.session import SessionWorkspace
from auralwarden.ui.assets import asset_path
from auralwarden.ui.styles import APP_STYLESHEET
from auralwarden.video_clips import cleanup_video_buffer, render_full_video_recording
from auralwarden.window_video import WindowPcmCapture, WindowTarget, window_target


class WindowRecordingDialog(QDialog):
    finished_recording = Signal(bool, str)

    def __init__(self, target: WindowTarget, audio_device: str = "", parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle(f"AuralWarden {__version__} — Grabación de ventana")
        self.resize(560, 230)
        self.stop_event = Event()
        self.source = WindowPcmCapture(target, audio_device)
        self.worker = None
        self.elapsed = 0.0
        self.done = False
        self.output_path: Path | None = None
        layout = QVBoxLayout(self)
        self.title_label = QLabel(target.title)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.status_label = QLabel("Preparando vídeo y audio del sistema…")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.time_label = QLabel("00:00:00")
        layout.addWidget(self.time_label)
        notice = QLabel("Solo se graba esta ventana. El audio del PC permanece audible.\n"
                        "Si cambias de pestaña en esta ventana, también quedará grabada.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.stop_button = QPushButton("Detener y guardar vídeo")
        self.stop_button.clicked.connect(self.stop_recording)
        layout.addWidget(self.stop_button)
        self.finished_recording.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(500)
        QTimer.singleShot(0, self.start_recording)

    def start_recording(self):
        if self.worker is not None:
            return
        self.worker = Thread(target=self._record, name="AuralWardenWindowRecording", daemon=True)
        self.worker.start()

    def _write_status(self, state: str, session: SessionWorkspace, detail: str = ""):
        destination = data_dir() / "window-recording-status.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps({"state": state, "version": __version__,
                                         "captured_seconds": self.elapsed,
                                         "session_path": str(session.path),
                                         "output_path": str(session.full_video_path),
                                         "detail": detail}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)

    def _record(self):
        session = None
        try:
            session = SessionWorkspace(sessions_dir(), f"window_capture://{self.target.hwnd}",
                                       Path(self.target.executable).stem)
            manifest = self.source.configure_video_buffer(session.video_buffer_dir)
            self._write_status("starting", session)
            last_space_check = 0.0
            for chunk in self.source.chunks(self.stop_event):
                self.elapsed = chunk.end_seconds
                if self.elapsed - last_space_check >= 5:
                    if shutil.disk_usage(session.path).free < 512 * 1024**2:
                        raise RuntimeError("Queda menos de 512 MiB en el disco; se conservarán los segmentos del vídeo.")
                    last_space_check = self.elapsed
                self._write_status("running", session)
            self._write_status("finalizing", session)
            self.output_path = render_full_video_recording(manifest, session.video_buffer_dir,
                                                          session.full_video_path)
            session.update_metadata(status="stopped", captured_seconds=self.elapsed,
                                    full_video=str(self.output_path))
            self._write_status("stopped", session)
            cleanup_video_buffer(session.video_buffer_dir, manifest)
            self.finished_recording.emit(True, str(self.output_path))
        except Exception as exc:
            if session is not None:
                session.update_metadata(status="failed", error=str(exc))
                self._write_status("failed", session, str(exc))
            self.finished_recording.emit(False, str(exc))
        finally:
            self.source.stop()

    def stop_recording(self):
        if self.done:
            self.close()
            return
        self.stop_event.set()
        self.source.stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("Finalizando y guardando el MP4…")

    def _refresh(self):
        seconds = int(self.elapsed)
        self.time_label.setText(f"{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}")
        if self.elapsed > 0 and not self.stop_event.is_set() and not self.done:
            self.status_label.setText("Grabando vídeo de esta ventana y audio del PC.")

    def _finished(self, success, message):
        self.done = True
        self.timer.stop()
        self.stop_button.setEnabled(True)
        self.stop_button.setText("Cerrar")
        self.status_label.setText(f"Vídeo guardado: {message}" if success else
                                  f"La grabación se interrumpió. Sus segmentos se conservaron: {message}")

    def closeEvent(self, event: QCloseEvent):
        if not self.done:
            self.stop_recording()
            event.ignore()
        else:
            event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Grabar una ventana y el audio del PC sin silenciarlo")
    parser.add_argument("--hwnd", type=int, required=True)
    args = parser.parse_args(argv)
    target = window_target(args.hwnd)
    app = QApplication.instance() or QApplication(sys.argv)
    from auralwarden.ui.app import _load_windows_ui_fonts, configure_application_identity
    configure_application_identity(app)
    app.setFont(QFont(_load_windows_ui_fonts(), 10))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    dialog = WindowRecordingDialog(target)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
