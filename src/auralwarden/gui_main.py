from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any


def _write_startup_error() -> None:
    destination = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    ) / "startup-error.log"
    try:
        destination.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass


def _run_self_check(destination: Path | None) -> int:
    modules = (
        "auralwarden.components",
        "auralwarden.hardware",
        "auralwarden.transcribers.whisper_cpp",
        "PySide6.QtCore",
        "streamlink",
        "yt_dlp",
        "pyaudiowpatch",
        "pycaw.pycaw",
        "comtypes.client",
        "faster_whisper",
        "ctranslate2",
        "sherpa_onnx",
    )
    from importlib.metadata import version
    from auralwarden import __version__
    if version("auralwarden") != __version__:
        raise RuntimeError("Los metadatos de la aplicación no coinciden con su versión.")
    report: dict[str, object] = {"version": __version__, "modules": {}}
    module_results = report["modules"]
    assert isinstance(module_results, dict)
    for module in modules:
        importlib.import_module(module)
        module_results[module] = "ok"

    from auralwarden.hardware import detect_hardware, hardware_summary, select_inference_plan
    from auralwarden.model_installer import model_manifest
    from auralwarden.paths import runtime_executable
    from auralwarden.windows_audio import list_windows_audio_devices

    capabilities = detect_hardware()
    plan = select_inference_plan(capabilities)
    ffmpeg = runtime_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg no está disponible dentro del paquete portable.")
    report["ffmpeg"] = ffmpeg
    report["hardware"] = {
        "physical_cores": capabilities.physical_cores,
        "logical_cores": capabilities.logical_cores,
        "memory_gb": capabilities.memory_gb,
        "gpus": [gpu.name for gpu in capabilities.gpus],
        "cuda_available": capabilities.cuda_available,
        "cuda_compute_types": list(capabilities.cuda_compute_types),
    }
    report["inference_plan"] = {
        "backend": plan.backend,
        "device": plan.device,
        "compute_type": plan.compute_type,
        "models": list(plan.model_candidates),
        "summary": hardware_summary(capabilities, plan),
    }
    report["system_audio_devices"] = len(list_windows_audio_devices("system_audio"))
    report["microphone_devices"] = len(list_windows_audio_devices("microphone"))
    catalog = model_manifest()
    if not catalog:
        raise RuntimeError("El catálogo verificado de modelos está vacío.")
    report["verified_model_catalog_entries"] = len(catalog)
    report["status"] = "ok"
    if destination is not None:
        resolved = destination.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


def _run_control_request(request_path: Path, destination: Path | None) -> int:
    try:
        request: Any = json.loads(request_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        response: dict[str, Any] = {
            "ok": False,
            "code": "invalid_request_file",
            "message": str(exc),
        }
    else:
        if not isinstance(request, dict):
            response = {
                "ok": False,
                "code": "invalid_request_file",
                "message": "La solicitud debe ser un objeto JSON.",
            }
        else:
            from PySide6.QtCore import QCoreApplication

            from auralwarden.local_control import (
                CONTROL_PROTOCOL_VERSION,
                LocalControlCredentialStore,
            )
            from auralwarden.paths import local_control_credentials_path
            from auralwarden.ui.app import send_local_control_request

            control_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
            safe_request = dict(request)
            safe_request["protocol_version"] = CONTROL_PROTOCOL_VERSION
            safe_request["token"] = LocalControlCredentialStore(
                local_control_credentials_path()
            ).read()
            response = send_local_control_request(safe_request)
            del control_app
    if destination is not None:
        resolved = destination.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if bool(response.get("ok")) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interfaz gráfica de AuralWarden")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--screenshot-delay-ms", type=int, default=12_000)
    parser.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-check-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--control-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--control-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            return _run_self_check(args.self_check_output)
        if args.control_request:
            return _run_control_request(args.control_request, args.control_output)
        from auralwarden.ui import run_app

        return run_app(
            demo=args.demo,
            screenshot=args.screenshot,
            screenshot_delay_ms=args.screenshot_delay_ms,
        )
    except Exception:
        _write_startup_error()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
