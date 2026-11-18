from __future__ import annotations

from pathlib import Path
from threading import Event
from bisect import bisect_right
import os

from PySide6.QtCore import QRect, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QSlider,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from auralwarden.filenames import elapsed_label, unique_path
from auralwarden.media_review import (MediaTimeline, export_interval, format_time,
    load_timeline, parse_time, validate_media)
from auralwarden.transcript_review import TranscriptSpan
from auralwarden.ui.typography import ParagraphTextEdit, justify_label


class ReviewTranscriptEdit(ParagraphTextEdit):
    timeRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spans: list[TranscriptSpan] = []
        self._time_spans = []
        self._times = []
        self._starts = []
        self._marked = None
        self._press = None

    def set_spans(self, spans):
        self.spans = list(spans)
        self._starts = [span.start for span in self.spans]
        self._time_spans = sorted(self.spans, key=lambda span: span.seconds)
        self._times = [span.seconds for span in self._time_spans]
        self._marked = None
        self.setExtraSelections([])

    def mousePressEvent(self, event):
        self._press = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (self._press is None or event.button() != Qt.MouseButton.LeftButton
                or (event.position().toPoint() - self._press).manhattanLength() > 4
                or self.textCursor().hasSelection()):
            return
        position = self.cursorForPosition(event.position().toPoint()).position()
        index = bisect_right(self._starts, position) - 1
        if index >= 0 and position <= self.spans[index].end:
            self.timeRequested.emit(self.spans[index].seconds)

    def mark_time(self, seconds: float):
        index = bisect_right(self._times, seconds) - 1
        if index < 0:
            self.setExtraSelections([])
            self._marked = None
            return
        span = self._time_spans[index]
        if span == self._marked:
            return
        self._marked = span
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(self.document())
        selection.cursor.setPosition(span.start)
        selection.cursor.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
        selection.format = QTextCharFormat()
        selection.format.setBackground(QColor("#164838"))
        self.setExtraSelections([selection])


class ExportWorker(QThread):
    outcome = Signal(object)

    def __init__(self, source, destination, start, end, parent=None, *, session_start=None):
        super().__init__(parent)
        self.source, self.destination = source, destination
        self.start_seconds, self.end_seconds = start, end
        self.session_start = session_start
        self.cancel = Event()

    def run(self):
        try:
            path = export_interval(self.source, self.destination, self.start_seconds, self.end_seconds,
                                   cancel=self.cancel, session_start=self.session_start)
            self.outcome.emit((path, None))
        except Exception as exc:
            self.outcome.emit((None, str(exc)))


class StillFrame(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self.image is not None and not self.image.isNull():
            size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            rectangle = QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2,
                              size.width(), size.height())
            painter.drawImage(rectangle, self.image)


class MediaReviewPanel(QWidget):
    timeChanged = Signal(float)
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source: Path | None = None
        self.timeline = MediaTimeline()
        self.duration = 0.0
        self.worker = None
        self._player = None
        self._audio = None
        self._pending_seek = None
        self._pending_close = None
        self._video_widget = None
        self._screen = None
        self._snapshot = None
        self._last_frame = None
        self._interval_initialized = False
        if QApplication.instance() is not None:
            QApplication.instance().aboutToQuit.connect(self._application_quit)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 3, 0, 0)
        file_row = QHBoxLayout()
        self.file_label = QLabel("No se encontró una grabación completa asociada.")
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        justify_label(self.file_label)
        file_row.addWidget(self.file_label, 1)
        self.choose = QPushButton("Elegir vídeo / audio")
        self.choose.clicked.connect(self.choose_media)
        file_row.addWidget(self.choose)
        layout.addLayout(file_row)
        self.video_container = QVBoxLayout()
        layout.addLayout(self.video_container)
        self.position = QLabel("Sesión: 00:00:00.000 · Archivo: 00:00:00.000")
        layout.addWidget(self.position)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1_000_000)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(lambda value: self._seek_media(value / 1_000_000 * self.duration))
        layout.addWidget(self.slider)
        controls = QHBoxLayout()
        self.play = QPushButton("Reproducir")
        self.play.setEnabled(False)
        self.play.clicked.connect(self.toggle_play)
        controls.addWidget(self.play)
        self.muted = QCheckBox("Silencio")
        self.muted.setChecked(True)
        self.muted.setToolTip("Solo silencia este reproductor, no Windows ni la aplicación vigilada.")
        self.muted.toggled.connect(lambda value: self._audio.setMuted(value) if self._audio else None)
        controls.addWidget(self.muted)
        self.goto = QLineEdit("00:00:00")
        self.goto.setMaximumWidth(130)
        self.goto.setToolTip("Tiempo de la sesión: HH:MM:SS o HH:MM:SS.mmm")
        controls.addWidget(self.goto)
        seek = QPushButton("Ir al tiempo")
        seek.clicked.connect(self.goto_time)
        self.goto.returnPressed.connect(self.goto_time)
        controls.addWidget(seek)
        controls.addStretch()
        layout.addLayout(controls)
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-86400, 86400)
        self.shift.setDecimals(3)
        self.shift.setSuffix(" s")
        self.shift.setToolTip("Tiempo de sesión = tiempo indicado por el índice + este desfase. No modifica el archivo.")
        self.shift.valueChanged.connect(lambda _: self._position_changed(self._player.position()) if self._player else None)
        form = QFormLayout()
        form.addRow("Desfase manual", self.shift)
        layout.addLayout(form)
        interval = QHBoxLayout()
        self.start = QLineEdit("00:00:00.000")
        self.end = QLineEdit("00:00:30.000")
        for field, label in ((self.start, "Inicio"), (self.end, "Fin")):
            field.setMaximumWidth(140)
            field.setToolTip("Tiempo de la sesión en HH:MM:SS.mmm")
            interval.addWidget(QLabel(label))
            interval.addWidget(field)
        mark_start = QPushButton("Marcar inicio")
        mark_start.clicked.connect(lambda: self.mark_interval(self.start))
        mark_end = QPushButton("Marcar fin")
        mark_end.clicked.connect(lambda: self.mark_interval(self.end))
        interval.addWidget(mark_start)
        interval.addWidget(mark_end)
        layout.addLayout(interval)
        exports = QHBoxLayout()
        self.export = QPushButton("Exportar intervalo como clip")
        self.export.setEnabled(False)
        self.export.clicked.connect(self.export_clip)
        exports.addWidget(self.export)
        self.cancel_export = QPushButton("Cancelar exportación")
        self.cancel_export.setEnabled(False)
        self.cancel_export.clicked.connect(lambda: self.worker.cancel.set() if self.busy else None)
        exports.addWidget(self.cancel_export)
        exports.addStretch()
        layout.addLayout(exports)
        self.status = QLabel("Selecciona una grabación local. No se reproduce ni exporta nada automáticamente.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        justify_label(self.status)
        layout.addWidget(self.status)

    @property
    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def _ensure_player(self):
        if self._player is not None:
            return
        # This player reads user-selected files, never nested network playlists.
        os.environ["QT_FFMPEG_PROTOCOL_WHITELIST"] = "file,pipe"
        os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(self.muted.isChecked())
        self._audio.setVolume(0.7)
        self._player.setAudioOutput(self._audio)
        self._video_widget = QVideoWidget()
        self._video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._screen = QStackedWidget()
        self._screen.setMinimumHeight(160)
        self._screen.setMaximumHeight(260)
        self._snapshot = StillFrame()
        self._screen.addWidget(self._video_widget)
        self._screen.addWidget(self._snapshot)
        self._screen.hide()
        self._player.setVideoOutput(self._video_widget)
        self.video_container.addWidget(self._screen)
        self._video_widget.videoSink().videoFrameChanged.connect(self._remember_frame)
        self._player.positionChanged.connect(self._position_changed)
        self._player.durationChanged.connect(self._duration_changed)
        self._player.mediaStatusChanged.connect(self._media_status)
        self._player.hasVideoChanged.connect(self._screen.setVisible)
        self._player.playbackStateChanged.connect(self._playback_changed)
        self._player.errorOccurred.connect(lambda *_: self.status.setText(
            "No se pudo reproducir este archivo. Comprueba que esté completo y tenga un formato compatible."))

    def _remember_frame(self, frame):
        if not frame.isValid() or self.source is None:
            return
        from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame
        self._last_frame = QVideoFrame(frame)
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._show_snapshot()

    def _show_snapshot(self):
        if self.source is None or self._last_frame is None:
            return
        image = self._last_frame.toImage()
        if not image.isNull():
            self._snapshot.image = image.scaled(1280, 720, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
            self._snapshot.update()
            self._screen.setCurrentWidget(self._snapshot)

    def _playback_changed(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setText("Pausar" if playing else "Reproducir")
        if playing:
            self._screen.setCurrentWidget(self._video_widget)
        else:
            self._show_snapshot()

    def load_media(self, path: Path) -> bool:
        if self.busy:
            return False
        try:
            path = validate_media(path)
            timeline = load_timeline(path)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return False
        self.reset()
        self._ensure_player()
        self.source, self.timeline = path, timeline
        self.shift.setValue(0)
        self.file_label.setText(path.name)
        self.file_label.setToolTip(str(path))
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self.status.setText("Índice temporal disponible. Pulsa una frase o introduce una hora."
            if timeline.known else "Grabación sin índice temporal: se supone inicio en 00:00:00. Ajusta el desfase si no coincide; en TXT la precisión es por párrafo.")
        return True

    def choose_media(self):
        selected, _ = QFileDialog.getOpenFileName(self, "Elegir grabación local", "",
            "Grabaciones (*.mp4 *.mkv *.mov *.webm *.wav *.mp3 *.m4a *.flac *.ogg)")
        if selected:
            self.load_media(Path(selected))

    def reset(self):
        if self.busy:
            return
        self.source = None
        self.timeline = MediaTimeline()
        self.duration = 0.0
        self._interval_initialized = False
        self._pending_seek = None
        if self._player:
            self._player.stop()
            self._player.setSource(QUrl())
        self._last_frame = None
        if self._snapshot:
            self._snapshot.image = None
            self._snapshot.update()
            self._screen.hide()
        self.file_label.setText("No se encontró una grabación completa asociada.")
        self.file_label.setToolTip("")
        self.play.setEnabled(False)
        self.export.setEnabled(False)
        self.slider.setEnabled(False)
        self.position.setText("Sesión: 00:00:00.000 · Archivo: 00:00:00.000")
        self.status.setText("Selecciona una grabación local. No se reproduce ni exporta nada automáticamente.")

    def _duration_changed(self, milliseconds):
        self.duration = max(0.0, milliseconds / 1000)
        available = self.source is not None and self.duration > 0
        self.play.setEnabled(available)
        self.slider.setEnabled(available)
        self.export.setEnabled(available and not self.busy)
        if available and not self._interval_initialized:
            self._interval_initialized = True
            try:
                first = max(0, self.timeline.to_session(0, self.shift.value()))
                if self.timeline.parts:
                    part = self.timeline.parts[0]
                    last = min(part.session_end, part.session_start + min(30, self.duration)) + self.shift.value()
                else:
                    last = min(30, self.duration) + self.shift.value()
                self.start.setText(format_time(first))
                self.end.setText(format_time(max(first, last)))
            except ValueError:
                self.start.setText("00:00:00.000")
                self.end.setText(format_time(min(30, self.duration)))

    def _media_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            if self._pending_seek is not None:
                value, self._pending_seek = self._pending_seek, None
                self.seek_session(value)

    def seek_session(self, seconds: float):
        if self.source is None:
            self.status.setText("Abre o elige primero el vídeo o audio de esta transcripción.")
            return False
        if not self.duration:
            self._pending_seek = seconds
            return True
        try:
            target = self.timeline.to_media(seconds, self.shift.value())
            if target > self.duration + 0.05:
                raise ValueError("Ese instante supera la duración del archivo.")
            self._seek_media(target)
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        return True

    def _seek_media(self, seconds):
        if self._player and self.source and self.duration:
            from PySide6.QtMultimedia import QMediaPlayer
            if self._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
                self._player.pause()
            self._player.setPosition(round(max(0, min(self.duration, seconds)) * 1000))

    def goto_time(self):
        try:
            self.seek_session(parse_time(self.goto.text()))
        except ValueError as exc:
            self.status.setText(str(exc))

    def _position_changed(self, milliseconds):
        media = milliseconds / 1000
        try:
            session = self.timeline.to_session(media, self.shift.value())
            session_label = format_time(session) if session >= 0 else "antes del inicio de sesión"
            self.timeChanged.emit(session)
        except ValueError:
            session_label = "sin correspondencia"
        self.position.setText(f"Sesión: {session_label} · Archivo: {format_time(media)}")
        if self.duration and not self.slider.isSliderDown():
            self.slider.setValue(round(media / self.duration * 1_000_000))

    def toggle_play(self):
        if not self._player or not self.source:
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def mark_interval(self, field):
        if self._player and self.source:
            try:
                seconds = self.timeline.to_session(self._player.position() / 1000, self.shift.value())
                if seconds < 0:
                    raise ValueError("El archivo está antes del inicio de sesión.")
                field.setText(format_time(seconds))
            except ValueError as exc:
                self.status.setText(str(exc))

    def export_clip(self):
        if self.busy or self.source is None or not self.duration:
            return
        try:
            session_start, session_end = parse_time(self.start.text()), parse_time(self.end.text())
            start, end = self.timeline.interval(session_start, session_end, self.shift.value())
            if end > self.duration + 0.05:
                raise ValueError("El intervalo supera la duración del archivo.")
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        suffix = ".mp4" if self._player.hasVideo() else ".wav"
        suggested = unique_path(self.source.parent.parent / "clips" / ("video" if suffix == ".mp4" else "audio") /
            f"Clip manual - {elapsed_label(session_start)} a {elapsed_label(session_end)}{suffix}")
        selected, _ = QFileDialog.getSaveFileName(self, "Guardar clip sin reemplazar originales",
            str(suggested), "Vídeo MP4 (*.mp4)" if suffix == ".mp4" else "Audio WAV (*.wav)")
        if not selected:
            return
        self.worker = ExportWorker(self.source, Path(selected), start, end, self, session_start=session_start)
        self.worker.outcome.connect(self._export_outcome)
        self.worker.finished.connect(self._export_finished)
        self.export.setEnabled(False)
        self.choose.setEnabled(False)
        self.shift.setEnabled(False)
        self.cancel_export.setEnabled(True)
        self.status.setText("Exportando con dos hilos de codificación; puedes cancelar. El original no se modifica.")
        self.busyChanged.emit(True)
        self.worker.start()

    def _export_outcome(self, outcome):
        path, error = outcome
        self.status.setText(error if error else f"Clip guardado: {path.name}")
        self.status.setToolTip("" if error else str(path))

    def _export_finished(self):
        completed, self.worker = self.worker, None
        if completed is not None:
            completed.deleteLater()
        self.export.setEnabled(self.source is not None and self.duration > 0)
        self.choose.setEnabled(True)
        self.shift.setEnabled(True)
        self.cancel_export.setEnabled(False)
        self.busyChanged.emit(False)
        if self._pending_close is not None:
            callback, self._pending_close = self._pending_close, None
            self.reset()
            callback()

    def shutdown(self, callback):
        if self.busy:
            self._pending_close = callback
            self.worker.cancel.set()
            self.status.setText("Cancelando la exportación antes de cerrar…")
        else:
            self.reset()
            callback()

    def _application_quit(self):
        if self.busy:
            self.worker.cancel.set()
            self.worker.wait(25_000)
        if self._player:
            self._player.stop()
            self._player.setSource(QUrl())
