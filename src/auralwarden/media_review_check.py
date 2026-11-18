from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path


def run_media_review_check(source: Path, destination: Path | None) -> int:
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication
    from auralwarden import __version__
    from auralwarden.media_review import export_interval, probe_media, validate_media
    from auralwarden.ui.media_review import MediaReviewPanel

    source = validate_media(source)
    if destination is None:
        raise ValueError("Indica un archivo nuevo con --self-check-output.")
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink() or destination.resolve() == source:
        raise ValueError("El informe de prueba debe usar un nombre nuevo, distinto del original.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = source.stat()
    duration, video = probe_media(source)
    if duration < 0.5:
        raise ValueError("La prueba requiere una muestra de al menos medio segundo.")
    app = QApplication.instance() or QApplication([])
    panel = MediaReviewPanel()
    frames = []
    try:
        if not panel.load_media(source):
            raise RuntimeError(panel.status.text())
        deadline = time.monotonic() + 20
        while not panel.duration and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        if not panel.duration:
            raise RuntimeError("El reproductor no pudo leer la muestra local.")
        panel._video_widget.videoSink().videoFrameChanged.connect(
            lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
        panel._audio.setMuted(True)
        target = min(1.2, duration / 2)
        # This diagnostic uses the file clock even if its session index starts elsewhere.
        panel._seek_media(target)
        deadline = time.monotonic() + 12
        while video and not frames and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        if video and not frames:
            raise RuntimeError("El paquete no pudo decodificar un fotograma de la muestra.")
        if panel._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or not panel._audio.isMuted():
            raise RuntimeError("La prueba debe permanecer en pausa y sin audio audible.")
        with tempfile.TemporaryDirectory(prefix="review-check-", dir=destination.parent) as folder:
            clip = Path(folder) / ("clip.mp4" if video else "clip.wav")
            export_interval(source, clip, 0.1, min(duration, 0.8))
            exported_duration, exported_video = probe_media(clip)
            if exported_video != video or abs(exported_duration - (min(duration, 0.8) - 0.1)) > 0.25:
                raise RuntimeError("La exportación de prueba no coincide con el intervalo solicitado.")
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise RuntimeError("La muestra original cambió durante la prueba.")
        report = {"version": __version__, "status": "ok", "duration_seconds": duration,
                  "video": video, "frame_decoded": bool(frames), "muted": True,
                  "paused": True, "export_verified": True, "original_unchanged": True}
        with destination.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
    finally:
        panel.reset()
        panel.close()
        panel.deleteLater()
        app.processEvents()
    return 0
