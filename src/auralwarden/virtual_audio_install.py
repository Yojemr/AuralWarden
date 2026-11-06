from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path

from auralwarden.components import ComponentManager, ComponentSpec, ComponentInstallError


VB_CABLE = ComponentSpec(
    component_id="vb-cable", version="pack45",
    url="https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
    sha256="b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb",
    executable_names=("VBCABLE_Setup_x64.exe",),
)
INSTALLER_HASH = "734c35dfa6d98f48782a451633ceb471166ec70d60482fd89a1123d0ee3c4f41"


def prepare_vb_cable(root: Path) -> Path:
    manager = ComponentManager(root)
    executable = manager.find_executable(VB_CABLE) or manager.install(VB_CABLE)
    if hashlib.sha256(executable.read_bytes()).hexdigest() != INSTALLER_HASH:
        raise ComponentInstallError("El instalador guardado no coincide con la versión oficial verificada.")
    return executable


def launch_vb_cable_installer(executable: Path) -> None:
    if os.name != "nt":
        raise ComponentInstallError("VB-CABLE requiere Windows.")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != INSTALLER_HASH:
        raise ComponentInstallError("El instalador cambió; no se ejecutará.")
    shell = ctypes.WinDLL("shell32", winmode=0x800)
    shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                   ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    result = shell.ShellExecuteW(None, "runas", str(executable), None, str(executable.parent), 1)
    if not result or result <= 32:
        raise ComponentInstallError("La instalación no se abrió o se canceló la autorización de administrador.")


def snapshot_audio_defaults():
    from pycaw.pycaw import AudioUtilities
    enumerator = AudioUtilities.GetDeviceEnumerator()
    result = []
    for flow in (0, 1):
        for role in (0, 1, 2):
            try:
                result.append((flow, role, str(enumerator.GetDefaultAudioEndpoint(flow, role).GetId())))
            except Exception:
                pass
    return result


def preserve_audio_defaults(previous):
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import ERole

    devices = {str(d.id): d for d in AudioUtilities.GetAllDevices()}
    current = {(flow, role): endpoint for flow, role, endpoint in snapshot_audio_defaults()}
    for flow, role, endpoint in previous:
        changed = current.get((flow, role), "")
        device = devices.get(changed)
        if (changed != endpoint and device is not None
                and "VB-Audio Virtual Cable" in str(device.FriendlyName)):
            AudioUtilities.SetDefaultDevice(endpoint, [ERole(role)])


def save_install_defaults(root: Path, defaults):
    from auralwarden.audio_routing import write_route_json
    write_route_json(root / "virtual-audio-install-state.json", {"defaults": defaults})


def recover_install_defaults(root: Path):
    from auralwarden.audio_routing import read_route_json, list_virtual_outputs
    path = root / "virtual-audio-install-state.json"
    state = read_route_json(path)
    if not state:
        return False
    previous = state.get("defaults")
    if (not isinstance(previous, list) or len(previous) > 6
            or any(not isinstance(row, (list, tuple)) or len(row) != 3
                   or row[0] not in (0, 1) or row[1] not in (0, 1, 2)
                   or not isinstance(row[2], str) or len(row[2]) > 1024 for row in previous)):
        raise ComponentInstallError("El registro de salidas previo a la instalación no es válido.")
    if not list_virtual_outputs():
        return False
    preserve_audio_defaults(previous)
    path.unlink(missing_ok=True)
    return True
