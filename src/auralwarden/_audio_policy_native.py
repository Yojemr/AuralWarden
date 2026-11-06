from __future__ import annotations

import ctypes as C
import os
from ctypes import wintypes as W

from auralwarden.windows_audio import WindowsAudioError


class NativeAudioPolicy:
    """Worker-local Windows per-application output preferences; never global defaults."""

    prefix = "\\\\?\\SWD#MMDEVAPI#"
    suffix = "#{e6327cad-dcec-4949-ae8a-991e976a79d2}"

    def __init__(self):
        if os.name != "nt":
            raise WindowsAudioError("El enrutamiento por aplicación requiere Windows.")
        from comtypes import GUID

        self.api = C.WinDLL("combase", winmode=0x800)
        self.api.RoInitialize.argtypes = [C.c_uint]
        self.api.RoInitialize.restype = C.c_long
        self.api.RoUninitialize.argtypes = []
        self.api.RoUninitialize.restype = None
        self.api.WindowsCreateString.argtypes = [W.LPCWSTR, W.UINT, C.POINTER(C.c_void_p)]
        self.api.WindowsCreateString.restype = C.c_long
        self.api.WindowsDeleteString.argtypes = [C.c_void_p]
        self.api.WindowsDeleteString.restype = C.c_long
        self.api.WindowsGetStringRawBuffer.argtypes = [C.c_void_p, C.POINTER(W.UINT)]
        self.api.WindowsGetStringRawBuffer.restype = C.c_void_p
        self.api.RoGetActivationFactory.argtypes = [C.c_void_p, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        self.api.RoGetActivationFactory.restype = C.c_long
        self.pointer = C.c_void_p()
        status = self.api.RoInitialize(1)
        self.initialized = status >= 0
        if status < 0 and status != -2147417850:
            self._check(status)
        name = self._string("Windows.Media.Internal.AudioPolicyConfig")
        try:
            for iid in ("ab3d4648-e242-459f-b02f-541c70306324", "2a59116d-6c4f-45e0-a74f-707e3fef9258"):
                status = self.api.RoGetActivationFactory(name, C.byref(GUID("{" + iid + "}")), C.byref(self.pointer))
                if status >= 0 and self.pointer:
                    break
            self._check(status)
            if not self.pointer:
                raise WindowsAudioError("Windows no expuso la interfaz de enrutamiento por aplicación.")
            table = C.cast(self.pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
            self._set = C.WINFUNCTYPE(C.c_long, C.c_void_p, W.DWORD, C.c_int, C.c_int, C.c_void_p)(table[25])
            self._get = C.WINFUNCTYPE(C.c_long, C.c_void_p, W.DWORD, C.c_int, C.c_int, C.POINTER(C.c_void_p))(table[26])
            self._release = C.WINFUNCTYPE(W.ULONG, C.c_void_p)(table[2])
        except BaseException:
            self.close()
            raise
        finally:
            self.api.WindowsDeleteString(name)

    @staticmethod
    def _check(status):
        if status < 0:
            raise WindowsAudioError(f"Windows rechazó el enrutamiento por aplicación (0x{status & 0xffffffff:08X}).")

    def _string(self, value):
        result = C.c_void_p()
        self._check(self.api.WindowsCreateString(value, len(value), C.byref(result)))
        return result

    def get(self, pid: int, role: int) -> str:
        output = C.c_void_p()
        try:
            self._check(self._get(self.pointer, pid, 0, role, C.byref(output)))
            if not output:
                return ""
            size = W.UINT()
            pointer = self.api.WindowsGetStringRawBuffer(output, C.byref(size))
            value = C.wstring_at(pointer, size.value) if pointer else ""
            return value.removeprefix(self.prefix).removesuffix(self.suffix)
        finally:
            if output:
                self.api.WindowsDeleteString(output)

    def set(self, pid: int, role: int, endpoint_id: str):
        value = self._string(self.prefix + endpoint_id + self.suffix) if endpoint_id else None
        try:
            self._check(self._set(self.pointer, pid, 0, role, value))
        finally:
            if value:
                self.api.WindowsDeleteString(value)

    def close(self):
        if self.pointer and hasattr(self, "_release"):
            self._release(self.pointer)
        self.pointer = C.c_void_p()
        if self.initialized:
            self.api.RoUninitialize()
            self.initialized = False
