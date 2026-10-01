from __future__ import annotations

import gc
import json
import time
from pathlib import Path
from typing import Any

from auralwarden.capture import CaptureConfig, FfmpegPcmCapture
from auralwarden.engine import MonitoringEngine
from auralwarden.events import EventBus
from auralwarden.hotwords import normalize_text
from auralwarden.models import AppSettings, EngineEvent, EventKind, Hotword, SessionState
from auralwarden.transcribers import FasterWhisperConfig, FasterWhisperTranscriber


def _run_profile(
    *,
    name: str,
    source: Path,
    model: str,
    language: str,
    hotwords: list[str],
    threshold: int,
    context: str,
    vocabulary: list[str],
    output: Path,
    device: str,
    compute_type: str,
) -> dict[str, Any]:
    legacy = name == "legacy"
    observed: list[EngineEvent] = []
    bus = EventBus()
    bus.subscribe(observed.append)
    settings = AppSettings(
        source_url=str(source),
        hotwords=[Hotword(value, threshold=threshold) for value in hotwords],
        model_name=model,
        inference_device=device,
        compute_type=compute_type,
        language=language,
        transcription_window_seconds=8.0 if legacy else 6.0,
        transcription_overlap_seconds=1.0 if legacy else 2.0,
        low_confidence_second_pass_threshold=0.0 if legacy else 0.62,
        rescue_empty_windows=not legacy,
        recognition_context=context,
        vocabulary=vocabulary,
        audio_buffer_seconds=30,
        video_buffer_seconds=30,
        save_event_audio_clips=False,
        auto_save_transcript=True,
    )
    config = FasterWhisperConfig(
        model_name=model,
        device=device,
        compute_type=compute_type,
        language=language,
        hotwords=hotwords,
        vocabulary=vocabulary,
        initial_prompt=context,
        local_files_only=True,
        vad_parameters=(
            {"min_silence_duration_ms": 350, "speech_pad_ms": 200}
            if legacy
            else {
                "threshold": 0.35,
                "min_speech_duration_ms": 100,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 350,
            }
        ),
        high_precision_vad_filter=legacy,
        repetition_penalty=1.0 if legacy else 1.05,
    )
    engine = MonitoringEngine(
        FfmpegPcmCapture(CaptureConfig(str(source))),
        FasterWhisperTranscriber(config),
        settings,
        session_root=output / name,
        event_bus=bus,
    )
    started = time.perf_counter()
    engine.run_foreground()
    elapsed = time.perf_counter() - started
    if engine.state != SessionState.STOPPED or engine.session is None:
        raise RuntimeError(engine.error or f"El perfil {name} no terminó correctamente.")
    text = " ".join(entry.text for entry in engine.transcript.entries)
    detections = [
        event.payload for event in observed if event.kind == EventKind.HOTWORD
    ]
    return {
        "profile": name,
        "window_seconds": settings.transcription_window_seconds,
        "overlap_seconds": settings.transcription_overlap_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "transcript_entries": len(engine.transcript.entries),
        "second_pass_entries": sum(
            1 for entry in engine.transcript.entries if entry.second_pass
        ),
        "detected_hotwords": sorted(
            {str(event["phrase"]) for event in detections}
        ),
        "transcript": text,
        "session": str(engine.session.path),
    }


def compare_audio_profiles(
    source: Path,
    *,
    model: str,
    language: str = "es",
    hotwords: list[str] | None = None,
    expected: list[str] | None = None,
    threshold: int = 88,
    context: str = "",
    vocabulary: list[str] | None = None,
    output: Path,
    device: str = "cuda",
    compute_type: str = "float16",
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ValueError("La comparación requiere un archivo local existente.")
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    expected = expected or []
    profiles = []
    for name in ("legacy", "high_recall"):
        profiles.append(
            _run_profile(
                name=name,
                source=source,
                model=model,
                language=language,
                hotwords=hotwords or [],
                threshold=threshold,
                context=context,
                vocabulary=vocabulary or [],
                output=output,
                device=device,
                compute_type=compute_type,
            )
        )
        gc.collect()

    for profile in profiles:
        normalized = normalize_text(profile["transcript"])
        profile["expected_phrases"] = {
            phrase: normalize_text(phrase) in normalized for phrase in expected
        }
        alerted = {normalize_text(item) for item in profile["detected_hotwords"]}
        profile["expected_alerts"] = {
            phrase: normalize_text(phrase) in alerted for phrase in expected
        }
    report = {
        "source": str(source),
        "model": model,
        "language": language,
        "hotwords": hotwords or [],
        "expected": expected,
        "profiles": profiles,
    }
    report_path = output / "comparison.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["report"] = str(report_path)
    return report
