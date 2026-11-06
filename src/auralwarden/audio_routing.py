from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from auralwarden.process_audio import ProcessTarget, validate_process_target
from auralwarden.windows_audio import WindowsAudioError


@dataclass(frozen=True, slots=True)
class VirtualOutput:
    endpoint_id: str
    name: str


def list_virtual_outputs() -> list[VirtualOutput]:
    from pycaw.pycaw import AudioUtilities

    return [VirtualOutput(str(d.id), str(d.FriendlyName)) for d in AudioUtilities.GetAllDevices()
            if str(d.id).startswith("{0.0.0.") and str(d.state).endswith(".Active")
            and str(d.FriendlyName) == "CABLE Input (VB-Audio Virtual Cable)"]


def write_route_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_route_json(path: Path) -> dict:
    try:
        if path.stat().st_size > 16384:
            raise WindowsAudioError("El registro de enrutamiento supera el límite permitido.")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid route state")
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError) as exc:
        raise WindowsAudioError("El registro de recuperación de audio no es válido.") from exc


class NativeRouteBackend:
    def __init__(self):
        from auralwarden._audio_policy_native import NativeAudioPolicy

        self.policy = NativeAudioPolicy()
        self.user = psutil.Process().username()

    def candidate(self, root: ProcessTarget, *, recovering=False) -> ProcessTarget | None:
        from pycaw.pycaw import AudioUtilities
        from pycaw.api.audiopolicy import IAudioSessionControl2

        permitted = None
        if not recovering:
            try:
                validate_process_target(root)
                process = psutil.Process(root.pid)
                permitted = {root.pid, *(p.pid for p in process.children(recursive=True))}
            except (WindowsAudioError, psutil.Error):
                return None
        fallback = None
        for device in AudioUtilities.GetAllDevices():
            if not str(device.id).startswith("{0.0.0.") or not str(device.state).endswith(".Active"):
                continue
            try:
                sessions = device.AudioSessionManager.GetSessionEnumerator()
                for index in range(sessions.GetCount()):
                    session = sessions.GetSession(index).QueryInterface(IAudioSessionControl2)
                    pid = int(session.GetProcessId())
                    if pid <= 0 or (permitted is not None and pid not in permitted):
                        continue
                    try:
                        p = psutil.Process(pid)
                        if p.username() != self.user or p.exe().casefold() != root.executable.casefold():
                            continue
                        target = ProcessTarget(pid, p.create_time(), p.exe())
                        if int(session.GetState()) == 1:
                            return target
                        fallback = target
                    except psutil.Error:
                        continue
            except Exception:
                continue
        return fallback

    def available(self, endpoint_id):
        return any(item.endpoint_id == endpoint_id for item in list_virtual_outputs())

    def default_output(self, role):
        from pycaw.pycaw import AudioUtilities
        return str(AudioUtilities.GetDeviceEnumerator().GetDefaultAudioEndpoint(0, role).GetId())

    def routed_outputs(self, target):
        from pycaw.pycaw import AudioUtilities
        from pycaw.api.audiopolicy import IAudioSessionControl2
        validate_process_target(target)
        endpoints = set()
        for device in AudioUtilities.GetAllDevices():
            if not str(device.id).startswith("{0.0.0.") or not str(device.state).endswith(".Active"):
                continue
            try:
                sessions = device.AudioSessionManager.GetSessionEnumerator()
                for index in range(sessions.GetCount()):
                    session = sessions.GetSession(index).QueryInterface(IAudioSessionControl2)
                    if int(session.GetProcessId()) == target.pid and int(session.GetState()) == 1:
                        endpoints.add(str(device.id))
            except Exception:
                continue
        return endpoints

    def get(self, target, role):
        validate_process_target(target)
        return self.policy.get(target.pid, role)

    def set(self, target, role, endpoint_id):
        validate_process_target(target)
        self.policy.set(target.pid, role, endpoint_id)

    def close(self):
        self.policy.close()


class RouteTransaction:
    """A journaled, compare-before-restore change to one application's preferences."""

    def __init__(self, path: Path, backend):
        self.path, self.backend = path, backend
        self.state = read_route_json(path)
        self.root = ProcessTarget(**self.state["target"])
        self.endpoint = str(self.state["endpoint_id"])
        self.lease = str(self.state["lease"])
        if not 16 <= len(self.lease) <= 128 or not self.endpoint.startswith("{0.0.0."):
            raise WindowsAudioError("El registro de enrutamiento no identifica un destino válido.")
        self.originals = self.state.get("originals", {})
        if not isinstance(self.originals, dict) or set(self.originals) - {"0", "1", "2"}:
            raise WindowsAudioError("Preferencias de audio guardadas inválidas.")
        if any(not isinstance(value, str) or len(value) > 1024 for value in self.originals.values()):
            raise WindowsAudioError("Preferencias de audio guardadas inválidas.")

    def _save(self, phase, error=""):
        self.state.update(phase=phase, error=error, originals=self.originals)
        write_route_json(self.path, self.state)

    def activate(self):
        if self.originals:
            raise WindowsAudioError("Hay una restauración de audio pendiente.")
        validate_process_target(self.root)
        if not self.backend.available(self.endpoint):
            raise WindowsAudioError("VB-CABLE no está disponible. Instálalo o reinicia Windows si lo solicita.")
        target = self.backend.candidate(self.root)
        if target is None:
            raise WindowsAudioError("La aplicación aún no tiene una sesión de audio compatible. Reproduce audio primero.")
        self.originals = {str(role): self.backend.get(target, role) for role in (0, 1, 2)}
        if self.endpoint in self.originals.values():
            self.originals = {}
            raise WindowsAudioError("Esta aplicación ya estaba enviada al cable. Restaura su salida antes de usar esta función.")
        if any(not self.originals[str(role)] and self.backend.default_output(role) == self.endpoint
               for role in (0, 1, 2)):
            self.originals = {}
            raise WindowsAudioError("El cable es una salida predeterminada de Windows. Elige primero tus altavoces como predeterminados.")
        self._save("preparing")
        try:
            for role in (0, 1, 2):
                self.backend.set(target, role, self.endpoint)
                if self.backend.get(target, role) != self.endpoint:
                    raise WindowsAudioError("Windows no confirmó el cambio de salida de la aplicación.")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if self.backend.routed_outputs(target) == {self.endpoint}:
                    break
                time.sleep(0.1)
            else:
                raise WindowsAudioError("La aplicación no cambió su audio al cable. Elige salida Predeterminada dentro de la aplicación, reproduce audio y reintenta.")
            self._save("active")
        except Exception:
            self.restore()
            raise

    def restore(self) -> bool:
        if not self.originals:
            self._save("restored")
            return True
        target = self.backend.candidate(self.root, recovering=True)
        if target is None:
            self._save("waiting", "Abre la aplicación original y reproduce audio para restaurar su salida.")
            return False
        pending = dict(self.originals)
        for role, original in self.originals.items():
            current = self.backend.get(target, int(role))
            if current == self.endpoint:
                self.backend.set(target, int(role), original)
                if self.backend.get(target, int(role)) != original:
                    raise WindowsAudioError("Windows no confirmó la restauración de la salida.")
            pending.pop(role)
            self.state["originals"] = pending
            write_route_json(self.path, self.state)
        deadline = time.monotonic() + 2
        while self.endpoint in self.backend.routed_outputs(target):
            if time.monotonic() >= deadline:
                self._save("waiting", "Las preferencias se restauraron, pero la aplicación sigue usando el cable. Elige Predeterminada en su salida de audio o vuelve a abrirla.")
                return False
            time.sleep(0.1)
        self.originals = {}
        self.state = {"lease": self.lease, "phase": "restored", "error": ""}
        write_route_json(self.path, self.state)
        return True

    def check_external_change(self):
        target = self.backend.candidate(self.root)
        if target is None or not self.backend.available(self.endpoint):
            return True
        return any(self.backend.get(target, role) != self.endpoint for role in (0, 1, 2))


class ApplicationAudioRouter:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.request_path = state_path.with_name(state_path.stem + "-request.json")
        self.process = None

    @property
    def state(self):
        try:
            return read_route_json(self.state_path)
        except (WindowsAudioError, OSError) as exc:
            return {"phase": "pending", "error": str(exc)}

    @property
    def active(self):
        value = self.state
        return value.get("phase") in {"requested", "preparing", "active", "restoring", "waiting", "pending"}

    @property
    def status_message(self):
        return str(self.state.get("error") or "")

    def _launch(self):
        if self.process is not None and self.process.poll() is None:
            raise WindowsAudioError("El auxiliar de restauración de audio sigue activo.")
        args = ([sys.executable, "--audio-route-guard", str(self.state_path)]
                if getattr(sys, "frozen", False) else
                [sys.executable, "-m", "auralwarden.audio_route_guard", str(self.state_path)])
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def activate(self, target: ProcessTarget, output: VirtualOutput):
        if self.active:
            raise WindowsAudioError("Restaura el audio pendiente antes de separar otra aplicación.")
        validate_process_target(target)
        if self.process is not None and self.process.poll() is None:
            self.process.wait(timeout=2)
        owner = psutil.Process()
        lease = secrets.token_hex(16)
        write_route_json(self.state_path, {"schema": 1, "lease": lease, "phase": "requested",
            "owner_pid": owner.pid, "owner_created_at": owner.create_time(),
            "target": asdict(target), "endpoint_id": output.endpoint_id, "originals": {}})
        self._launch()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.state
            if current.get("phase") == "active":
                return
            if current.get("phase") in {"failed", "restored", "waiting", "pending"}:
                raise WindowsAudioError(str(current.get("error") or "No se pudo separar el audio."))
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        self.restore_original(wait=False)
        raise WindowsAudioError("El cambio de salida no respondió a tiempo; se solicitó restauración.")

    def restore_original(self, *, wait=True):
        value = self.state
        if not self.active and value.get("phase") != "requested":
            return False
        write_route_json(self.request_path, {"lease": value.get("lease"), "command": "restore"})
        self._ensure_guard()
        if wait:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = self.state
                if current.get("phase") == "restored":
                    return True
                if current.get("phase") == "failed":
                    raise WindowsAudioError(str(current.get("error") or "Restauración pendiente."))
                time.sleep(0.05)
            raise WindowsAudioError(str(self.state.get("error") or "La restauración sigue pendiente en el auxiliar de audio."))
        return True

    def reveal_for_alert(self):
        return self.restore_original()

    def recover_interrupted(self):
        value = self.state
        if not self.active:
            return False
        owner_running = False
        try:
            owner = psutil.Process(int(value["owner_pid"]))
            owner_running = owner.create_time() == value["owner_created_at"] and owner.is_running()
        except (KeyError, ValueError, TypeError, psutil.Error):
            pass
        if owner_running and int(value.get("owner_pid", 0)) != os.getpid():
            raise WindowsAudioError("Otra instancia está restaurando el audio. No se tomará control de su sesión.")
        self.restore_original(wait=False)
        return True

    def _ensure_guard(self):
        if self.process is not None and self.process.poll() is None:
            return
        value = self.state
        try:
            guard = psutil.Process(int(value.get("guard_pid", 0)))
            if guard.is_running() and guard.create_time() == value.get("guard_created_at"):
                return
        except (ValueError, TypeError, psutil.Error):
            pass
        self._launch()
