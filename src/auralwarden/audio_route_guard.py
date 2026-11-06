from __future__ import annotations

import sys
import time
import ctypes as C
import hashlib
from ctypes import wintypes as W
from pathlib import Path

import psutil

from auralwarden.audio_routing import NativeRouteBackend, RouteTransaction, read_route_json, write_route_json


def run_guard(path: Path):
    sys.coinit_flags = 0
    backend = None
    transaction = None
    mutex = None
    kernel = None
    owns_route = False
    try:
        backend = NativeRouteBackend()
        transaction = RouteTransaction(path, backend)
        state = transaction.state
        kernel = C.WinDLL("kernel32", use_last_error=True, winmode=0x800)
        kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        kernel.CreateMutexW.restype = W.HANDLE
        kernel.CloseHandle.argtypes = [W.HANDLE]
        kernel.CloseHandle.restype = W.BOOL
        name = "Local\\AuralWarden.AudioRoute." + hashlib.sha256(transaction.root.executable.casefold().encode()).hexdigest()
        mutex = kernel.CreateMutexW(None, True, name)
        if not mutex or C.get_last_error() == 183:
            if mutex:
                kernel.CloseHandle(mutex)
                mutex = None
            return 1
        owns_route = True
        current_guard = psutil.Process()
        state.update(guard_pid=current_guard.pid, guard_created_at=current_guard.create_time())
        write_route_json(path, state)
        request_path = path.with_name(path.stem + "-request.json")
        command = read_route_json(request_path)
        restoring = state.get("phase") != "requested" or (
            command.get("lease") == transaction.lease and command.get("command") == "restore")
        if not restoring:
            owner = psutil.Process(int(state["owner_pid"]))
            if owner.create_time() != state["owner_created_at"] or not owner.is_running():
                transaction.restore()
                return 0
            transaction.activate()
        deadline = time.monotonic() + 86400
        while time.monotonic() < deadline:
            command = read_route_json(request_path)
            if command.get("lease") == transaction.lease and command.get("command") == "restore":
                restoring = True
            try:
                owner = psutil.Process(int(state["owner_pid"]))
                alive = owner.is_running() and owner.create_time() == state["owner_created_at"]
            except (KeyError, ValueError, TypeError, psutil.Error):
                alive = False
            if not alive:
                restoring = True
            if not restoring and transaction.check_external_change():
                restoring = True
            if restoring and transaction.restore():
                return 0
            time.sleep(1.0 if restoring else 0.25)
        transaction._save("pending", "Restauración pendiente: abre la aplicación original y vuelve a abrir AuralWarden.")
        return 1
    except Exception as exc:
        if transaction is not None and transaction.originals and owns_route:
            try:
                if transaction.restore():
                    return 1
            except Exception:
                pass
            transaction._save("pending", str(exc))
        elif owns_route or transaction is None:
            state = read_route_json(path)
            state.update(phase="failed", error=str(exc))
            write_route_json(path, state)
        return 1
    finally:
        if backend is not None:
            backend.close()
        if mutex is not None:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(run_guard(Path(sys.argv[1])))
