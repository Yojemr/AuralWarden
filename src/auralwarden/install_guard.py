from __future__ import annotations

import ctypes
import os


INSTALLED_MUTEX = r"Local\Yojemr.AuralWarden.Installed"


class InstalledAppGuard:
    """Prevents an installer from replacing a running installed application."""

    def __init__(self):
        self.handle = None

    def claim(self):
        if os.name != "nt":
            return
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, True, INSTALLED_MUTEX)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, "No se pudo proteger la instalación en uso.")
        if error == 183:
            self.kernel.CloseHandle(handle)
            raise RuntimeError("La instalación de AuralWarden está en uso. Espera a que termine la otra instancia o su actualización.")
        self.handle = handle

    def close(self):
        if self.handle is not None:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
