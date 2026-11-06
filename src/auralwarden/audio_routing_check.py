from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread, Timer


def _renderer_pid(stdout, timeout=10):
    result = Queue(maxsize=1)

    def read():
        try:
            result.put(json.loads(stdout.readline(1024))["pid"])
        except Exception as exc:
            result.put(exc)

    Thread(target=read, daemon=True).start()
    try:
        value = result.get(timeout=timeout)
    except Empty as exc:
        raise RuntimeError("El generador sintético no respondió a tiempo.") from exc
    if isinstance(value, Exception):
        raise RuntimeError("El generador sintético no pudo iniciarse.") from value
    return int(value)


def synthetic_renderer():
    import numpy as np
    import pyaudiowpatch as pa
    from auralwarden._audio_policy_native import NativeAudioPolicy
    from auralwarden.audio_routing import list_virtual_outputs

    cable = list_virtual_outputs()
    if len(cable) != 1:
        return 1
    manager = pa.PyAudio()
    stream = None
    policy = NativeAudioPolicy()
    last = None
    rate = 44100
    print(json.dumps({"pid": os.getpid()}), flush=True)
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if stream is None:
                stream = manager.open(format=pa.paInt16, channels=2, rate=44100, output=True,
                                      frames_per_buffer=441)
                stream.write(bytes(17640))
            destination = policy.get(os.getpid(), 1)
            if destination != last:
                stream.close()
                kwargs = {}
                if destination == cable[0].endpoint_id:
                    wasapi = manager.get_host_api_info_by_type(pa.paWASAPI)
                    found = [d for d in manager.get_device_info_generator()
                             if d.get("hostApi") == wasapi["index"] and d.get("maxOutputChannels", 0) > 0
                             and d.get("name") == cable[0].name]
                    if len(found) != 1:
                        raise RuntimeError("Synthetic cable device not unique")
                    kwargs["output_device_index"] = int(found[0]["index"])
                    rate = int(found[0]["defaultSampleRate"])
                else:
                    rate = int(manager.get_default_output_device_info()["defaultSampleRate"])
                stream = manager.open(format=pa.paInt16, channels=2, rate=rate, output=True,
                                      frames_per_buffer=rate // 100, **kwargs)
                last = destination
            if destination == cable[0].endpoint_id:
                samples = (np.sin(np.arange(rate // 10) * 2 * np.pi * 600 / rate) * 5000).astype(np.int16)
                data = np.repeat(samples[:, None], 2, axis=1).tobytes()
            else:
                data = bytes(rate // 10 * 4)
            stream.write(data)
    finally:
        if stream:
            stream.close()
        policy.close()
        manager.terminate()
    return 0


def run_routing_check(destination: Path | None):
    if destination is None:
        raise ValueError("Indica un archivo de diagnóstico.")
    import psutil
    from auralwarden import __version__
    from auralwarden._audio_policy_native import NativeAudioPolicy
    from auralwarden.audio_routing import ApplicationAudioRouter, list_virtual_outputs
    from auralwarden.process_audio import ProcessPcmCapture, ProcessTarget
    from auralwarden.windows_audio import _pcm_level
    from auralwarden.virtual_audio_install import snapshot_audio_defaults

    root = destination.resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    router = ApplicationAudioRouter(root / "synthetic-audio-route.json")
    defaults = snapshot_audio_defaults()
    report = {"version": __version__, "status": "failed", "audio_saved": False,
              "test_signal_output": "VB-CABLE only", "user_application_routes_changed": False}
    child = None
    policy = None
    try:
        args = ([sys.executable, "--synthetic-route-renderer"] if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "auralwarden.audio_routing_check", "renderer"])
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if not child.stdout:
            raise RuntimeError("No synthetic renderer output")
        # The renderer announces its real PID, not a possible Python launcher PID.
        pid = _renderer_pid(child.stdout)
        process = psutil.Process(pid)
        target = ProcessTarget(pid, process.create_time(), process.exe())
        policy = NativeAudioPolicy()
        deadline = time.monotonic() + 5
        while True:
            try:
                original = [policy.get(pid, role) for role in (0, 1, 2)]
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        if router.active:
            router.restore_original()
            if router.active:
                raise RuntimeError("Una comprobación anterior aún necesita restaurar su audio.")
            original = [policy.get(pid, role) for role in (0, 1, 2)]
        router.activate(target, list_virtual_outputs()[0])
        report["activation"] = "ok"
        source = ProcessPcmCapture(target)
        stop = Event()
        timer = Timer(5, stop.set)
        timer.start()
        levels = []
        try:
            for chunk in source.chunks(stop):
                levels.append(_pcm_level(chunk.data))
        finally:
            timer.cancel()
            source.stop()
        report["captured_rms"] = max(levels, default=0.0)
        if report["captured_rms"] < 0.03:
            raise RuntimeError("El audio virtual no llegó al capturador de la aplicación.")
        router.restore_original()
        if [policy.get(pid, role) for role in (0, 1, 2)] != original:
            raise RuntimeError("Las preferencias de la prueba no se restauraron.")
        report["restore"] = "ok"
        report["global_defaults_unchanged"] = snapshot_audio_defaults() == defaults
        if not report["global_defaults_unchanged"]:
            raise RuntimeError("Cambió un dispositivo predeterminado durante la comprobación.")
        report["status"] = "ok"
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if router.active:
            try:
                router.restore_original()
            except Exception as exc:
                report["restore_error"] = str(exc)
        if child is not None:
            # Never end a target while its application preference still needs restoration.
            if not router.active and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        if policy:
            policy.close()
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if sys.argv[1] == "renderer":
        raise SystemExit(synthetic_renderer())
    raise SystemExit(run_routing_check(Path(sys.argv[1])))
