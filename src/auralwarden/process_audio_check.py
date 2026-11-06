from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Timer


def run_process_capture_check(hwnd: int, destination: Path | None) -> int:
    if destination is None:
        raise ValueError("Indica un archivo de diagnóstico para la comprobación de audio.")
    from auralwarden import __version__
    from auralwarden.process_audio import ProcessPcmCapture, ProcessTarget
    from auralwarden.window_video import window_target
    from auralwarden.windows_audio import _pcm_level

    target = ProcessTarget.from_window(window_target(hwnd))
    source = ProcessPcmCapture(target)
    report = {"version": __version__, "status": "failed", "captured_seconds": 0.0,
              "maximum_rms": 0.0, "connected": False, "audio_saved": False,
              "changed_volume": False}
    source.set_status_callback(lambda phase, payload:
                              report.update(connected=True) if phase == "connected" else None)
    stop = Event()
    timer = Timer(8.0, stop.set)
    timer.start()
    try:
        for chunk in source.chunks(stop):
            report["captured_seconds"] = chunk.end_seconds
            report["maximum_rms"] = max(report["maximum_rms"], _pcm_level(chunk.data))
        if report["connected"] and report["captured_seconds"] >= 3:
            report["status"] = "ok"
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        timer.cancel()
        source.stop()
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
