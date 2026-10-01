from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import platform
import sys
from pathlib import Path
from threading import Event, Timer

from auralwarden import __version__
from auralwarden.capture import CaptureConfig, FfmpegPcmCapture, MemoryPcmCapture
from auralwarden.captions import YoutubeCaptionSource, is_youtube_source
from auralwarden.cuda import find_nvidia_bin_directories
from auralwarden.diarization import (
    SherpaDiarizerConfig,
    SherpaOnnxDiarizer,
    download_diarization_models,
)
from auralwarden.engine import MonitoringEngine
from auralwarden.evaluation import compare_audio_profiles
from auralwarden.events import EventBus
from auralwarden.models import AppSettings, EngineEvent, EventKind, Hotword, SessionState
from auralwarden.paths import runtime_executable
from auralwarden.transcribers import (
    FasterWhisperConfig,
    FasterWhisperTranscriber,
    ScriptedTranscriber,
)


def _configure_console_encoding() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _speaker_name(value: str) -> tuple[str, str]:
    speaker, separator, display_name = value.partition("=")
    if not separator or not speaker.strip() or not display_name.strip():
        raise argparse.ArgumentTypeError(
            "Use el formato 'Speaker 1=Nombre visible'."
        )
    return speaker.strip(), display_name.strip()


def diagnostics() -> dict[str, object]:
    report: dict[str, object] = {
        "auralwarden": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": runtime_executable("ffmpeg"),
        "nvidia_smi": runtime_executable("nvidia-smi"),
        "optional_modules": {
            "streamlink": _module_available("streamlink"),
            "faster_whisper": _module_available("faster_whisper"),
            "numpy": _module_available("numpy"),
            "rapidfuzz": _module_available("rapidfuzz"),
            "psutil": _module_available("psutil"),
            "sherpa_onnx": _module_available("sherpa_onnx"),
        },
        "nvidia_library_paths": [
            str(path) for path in find_nvidia_bin_directories()
        ],
    }
    if _module_available("ctranslate2"):
        try:
            import ctranslate2

            report["cuda"] = {
                "device_count": ctranslate2.get_cuda_device_count(),
                "compute_types": sorted(ctranslate2.get_supported_compute_types("cuda")),
            }
        except Exception as exc:
            report["cuda"] = {"device_count": 0, "error": str(exc)}
    return report


def _print_event(event: EngineEvent) -> None:
    if event.kind == EventKind.TRANSCRIPT:
        elapsed = float(event.payload["elapsed_seconds"])
        speaker = event.payload["speaker_id"]
        print(f"[{elapsed:08.2f}] {speaker}: {event.payload['text']}")
    elif event.kind == EventKind.HOTWORD:
        status = "nueva" if event.payload["created"] else "fusionada"
        print(
            f"  HOTWORD {event.payload['phrase']} "
            f"({float(event.payload['score']):.1f}%, {status})"
        )
    elif event.kind == EventKind.CLIP:
        suffix = " (incompleto)" if event.payload["truncated"] else ""
        print(f"  CLIP {event.payload['path']}{suffix}")
    elif event.kind == EventKind.ERROR:
        print(f"ERROR: {event.payload['message']}", file=sys.stderr)


def _run_engine(engine: MonitoringEngine, seconds: float | None = None) -> int:
    engine.start()
    timer = Timer(seconds, engine.stop) if seconds and seconds > 0 else None
    if timer is not None:
        timer.daemon = True
        timer.start()
    try:
        while engine.running:
            engine.join(0.25)
    except KeyboardInterrupt:
        engine.stop()
        engine.join(10)
    finally:
        if timer is not None:
            timer.cancel()
    if engine.session is not None:
        print(f"Sesión: {engine.session.path}")
    return 0 if engine.state == SessionState.STOPPED else 1


def command_doctor(args: argparse.Namespace) -> int:
    report = diagnostics()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"AuralWarden {report['auralwarden']} — backend")
        print(f"Python: {report['python']}")
        print(f"FFmpeg: {report['ffmpeg'] or 'NO DISPONIBLE'}")
        print(f"NVIDIA: {report['nvidia_smi'] or 'NO DISPONIBLE'}")
        for name, available in report["optional_modules"].items():
            print(f"{name}: {'sí' if available else 'no'}")
        print(
            "Bibliotecas NVIDIA locales: "
            + (", ".join(report["nvidia_library_paths"]) or "no encontradas")
        )
        if "cuda" in report:
            print(f"CUDA para STT: {report['cuda']}")
    return 0 if report["ffmpeg"] else 1


def command_simulate(args: argparse.Namespace) -> int:
    lines = [
        ("Speaker 1", "Iniciamos el monitoreo local de esta transmisión."),
        ("Speaker 2", "La nueva licitación será publicada esta semana."),
        ("Speaker 1", "El contrato incluye medidas de transparencia."),
        ("Speaker 3", "Terminamos la prueba funcional de AuralWarden."),
    ]
    settings = AppSettings(
        source_url="demo://backend",
        hotwords=[Hotword("licitación"), Hotword("contrato")],
        video_buffer_seconds=30,
        audio_buffer_seconds=30,
        clip_pre_seconds=2,
        clip_post_seconds=2,
        transcription_window_seconds=3,
        transcription_overlap_seconds=0,
        auto_save_transcript=True,
        save_event_audio_clips=True,
    )
    bus = EventBus()
    bus.subscribe(_print_event)
    engine = MonitoringEngine(
        MemoryPcmCapture(duration_seconds=12, chunk_seconds=1),
        ScriptedTranscriber(lines),
        settings,
        session_root=Path(args.output).resolve() if args.output else None,
        event_bus=bus,
    )
    return _run_engine(engine)


def command_capture_test(args: argparse.Namespace) -> int:
    source = FfmpegPcmCapture(CaptureConfig(args.source, chunk_seconds=1.0))
    stop = Event()
    total = 0.0
    try:
        for chunk in source.chunks(stop):
            total = chunk.end_seconds
            if args.seconds and total >= args.seconds:
                stop.set()
                break
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        source.stop()
    print(f"PCM válido: mono, 16 kHz, {total:.2f} s")
    return 0


def command_monitor(args: argparse.Namespace) -> int:
    hotwords = [Hotword(value, threshold=args.threshold) for value in args.hotword]
    settings = AppSettings(
        source_url=args.source,
        hotwords=hotwords,
        model_name=args.model,
        inference_device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        transcription_window_seconds=args.window,
        transcription_overlap_seconds=args.overlap,
        low_confidence_second_pass_threshold=args.low_confidence_threshold,
        recognition_context=args.context,
        vocabulary=args.vocabulary,
        diarization_enabled=args.diarize,
        diarization_segmentation_model=(
            str(Path(args.diarization_model_dir) / "segmentation.onnx")
            if args.diarize
            else ""
        ),
        diarization_embedding_model=(
            str(Path(args.diarization_model_dir) / "embedding.onnx")
            if args.diarize
            else ""
        ),
        diarization_num_speakers=args.speakers,
        diarization_cluster_threshold=args.diarization_cluster_threshold,
        speaker_match_threshold=args.speaker_match_threshold,
        diarization_threads=args.diarization_threads,
        speaker_names=dict(args.speaker_name),
        video_buffer_seconds=args.buffer,
        audio_buffer_seconds=args.buffer,
        clip_pre_seconds=args.pre,
        clip_post_seconds=args.post,
        save_full_audio=args.save_full_audio,
        save_full_video=args.save_full_video,
        use_youtube_captions=not args.no_youtube_captions,
        save_event_video_clips=args.video_clips,
        auto_save_transcript=args.save_transcript,
    )
    config = FasterWhisperConfig(
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        hotwords=args.hotword,
        vocabulary=args.vocabulary,
        initial_prompt=args.context,
        download_root=args.model_dir,
        local_files_only=args.offline or not args.allow_model_download,
    )
    bus = EventBus()
    bus.subscribe(_print_event)
    diarizer = None
    if args.diarize:
        model_dir = Path(args.diarization_model_dir).expanduser().resolve()
        diarizer = SherpaOnnxDiarizer(
            SherpaDiarizerConfig(
                segmentation_model=str(model_dir / "segmentation.onnx"),
                embedding_model=str(model_dir / "embedding.onnx"),
                num_speakers=args.speakers,
                cluster_threshold=args.diarization_cluster_threshold,
                speaker_match_threshold=args.speaker_match_threshold,
                num_threads=args.diarization_threads,
            )
        )
    engine = MonitoringEngine(
        FfmpegPcmCapture(
            CaptureConfig(
                args.source,
                quality=(
                    "720p,480p,best"
                    if args.video_clips or args.save_full_video
                    else "audio_only,best"
                ),
            )
        ),
        FasterWhisperTranscriber(config),
        settings,
        session_root=Path(args.output).resolve() if args.output else None,
        event_bus=bus,
        diarizer=diarizer,
        caption_source=(
            YoutubeCaptionSource(args.source, args.language)
            if not args.no_youtube_captions and is_youtube_source(args.source)
            else None
        ),
    )
    return _run_engine(engine, args.seconds)


def command_download_model(args: argparse.Namespace) -> int:
    try:
        from faster_whisper.utils import download_model
    except ImportError:
        print("ERROR: faster-whisper no está instalado.", file=sys.stderr)
        return 1
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        model_path = download_model(args.model, output_dir=str(output))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Modelo disponible en: {model_path}")
    return 0


def command_download_diarization_models(args: argparse.Namespace) -> int:
    try:
        paths = download_diarization_models(Path(args.output), force=args.force)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Segmentación: {paths['segmentation']}")
    print(f"Embeddings: {paths['embedding']}")
    return 0


def command_compare_audio(args: argparse.Namespace) -> int:
    try:
        report = compare_audio_profiles(
            Path(args.source),
            model=args.model,
            language=args.language,
            hotwords=args.hotword,
            expected=args.expect,
            threshold=args.threshold,
            context=args.context,
            vocabulary=args.vocabulary,
            output=Path(args.output),
            device=args.device,
            compute_type=args.compute_type,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_gui(args: argparse.Namespace) -> int:
    try:
        from auralwarden.ui import run_app
    except ImportError:
        print(
            "ERROR: la interfaz no está instalada. Use scripts\\setup.ps1 -Profile ui.",
            file=sys.stderr,
        )
        return 1
    return run_app(demo=args.demo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auralwarden",
        description="Backend local de transcripción y alertas en vivo.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Comprueba herramientas y dependencias.")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    gui = commands.add_parser("gui", help="Abre la interfaz gráfica de Windows.")
    gui.add_argument("--demo", action="store_true", help="Usa una sesión local de demostración.")
    gui.set_defaults(handler=command_gui)

    simulate = commands.add_parser("simulate", help="Ejecuta el flujo sin Internet ni modelo.")
    simulate.add_argument("--output", help="Carpeta donde crear la sesión de prueba.")
    simulate.set_defaults(handler=command_simulate)

    capture = commands.add_parser("capture-test", help="Valida la captura y conversión PCM.")
    capture.add_argument("source", help="Archivo local o URL compatible con Streamlink.")
    capture.add_argument("--seconds", type=float, default=5.0)
    capture.set_defaults(handler=command_capture_test)

    download = commands.add_parser(
        "download-model", help="Descarga explícitamente un modelo local de Whisper."
    )
    download.add_argument("--model", default="large-v3-turbo")
    download.add_argument("--output", default="data/models/large-v3-turbo")
    download.set_defaults(handler=command_download_model)

    diarization_download = commands.add_parser(
        "download-diarization-models",
        help="Descarga los modelos ONNX locales para separar hablantes.",
    )
    diarization_download.add_argument(
        "--output", default="data/models/diarization"
    )
    diarization_download.add_argument("--force", action="store_true")
    diarization_download.set_defaults(handler=command_download_diarization_models)

    compare = commands.add_parser(
        "compare-audio",
        help="Compara el perfil anterior y el de alta recuperación sobre el mismo audio.",
    )
    compare.add_argument("source")
    compare.add_argument("--model", default="data/models/large-v3-turbo")
    compare.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    compare.add_argument("--compute-type", default="float16")
    compare.add_argument("--language", default="es")
    compare.add_argument("--hotword", action="append", default=[])
    compare.add_argument("--expect", action="append", default=[])
    compare.add_argument("--threshold", type=int, default=88)
    compare.add_argument("--context", default="")
    compare.add_argument("--vocabulary", action="append", default=[])
    compare.add_argument("--output", default="data/evaluations/latest")
    compare.set_defaults(handler=command_compare_audio)

    monitor = commands.add_parser("monitor", help="Monitoriza una fuente con faster-whisper.")
    monitor.add_argument("source")
    monitor.add_argument("--hotword", action="append", default=[])
    monitor.add_argument("--threshold", type=int, default=88)
    monitor.add_argument("--model", default="large-v3-turbo")
    monitor.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    monitor.add_argument("--compute-type", default="float16")
    monitor.add_argument("--language", default="es")
    monitor.add_argument("--window", type=float, default=6.0)
    monitor.add_argument("--overlap", type=float, default=2.0)
    monitor.add_argument("--low-confidence-threshold", type=float, default=0.62)
    monitor.add_argument("--context", default="")
    monitor.add_argument("--vocabulary", action="append", default=[])
    monitor.add_argument("--model-dir")
    monitor.add_argument("--offline", action="store_true")
    monitor.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Permite descargar el modelo si no existe localmente.",
    )
    monitor.add_argument("--buffer", type=int, default=60)
    monitor.add_argument("--pre", type=int, default=15)
    monitor.add_argument("--post", type=int, default=30)
    monitor.add_argument("--seconds", type=float)
    monitor.add_argument("--save-full-audio", action="store_true")
    monitor.add_argument(
        "--save-full-video",
        action="store_true",
        help="Guarda toda la fuente audiovisual en un MP4.",
    )
    monitor.add_argument(
        "--no-youtube-captions",
        action="store_true",
        help="Desactiva la fuente auxiliar de subtítulos de YouTube.",
    )
    monitor.add_argument(
        "--video-clips",
        action="store_true",
        help="Crea clips MP4 con audio al detectar una hotword.",
    )
    monitor.add_argument("--save-transcript", action="store_true")
    monitor.add_argument("--diarize", action="store_true")
    monitor.add_argument(
        "--diarization-model-dir", default="data/models/diarization"
    )
    monitor.add_argument(
        "--speakers",
        type=int,
        default=0,
        help="Número esperado de hablantes; 0 permite detección automática.",
    )
    monitor.add_argument(
        "--diarization-cluster-threshold", type=float, default=0.75
    )
    monitor.add_argument("--speaker-match-threshold", type=float, default=0.32)
    monitor.add_argument("--diarization-threads", type=int, default=2)
    monitor.add_argument(
        "--speaker-name",
        action="append",
        type=_speaker_name,
        default=[],
        help="Asigna un nombre manual, por ejemplo 'Speaker 1=Ana'.",
    )
    monitor.add_argument("--output")
    monitor.set_defaults(handler=command_monitor)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))
