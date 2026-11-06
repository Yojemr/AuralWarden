from __future__ import annotations

import ctypes as C
import sys
import time
from ctypes import wintypes as W
from threading import Event

from auralwarden.windows_audio import WindowsAudioError


class NativeProcessLoopback:
    """Worker-local WASAPI process loopback. Never changes a render endpoint."""

    sample_rate = 44100
    channels = 2

    def __init__(self, pid: int, stop_event, timeout: float = 8.0):
        sys.coinit_flags = 0
        import comtypes as COM
        from pycaw.api.audioclient import IAudioClient
        from pycaw.api.audioclient.depend import WAVEFORMATEX

        class Activation(C.Structure):
            _fields_ = [("kind", W.DWORD), ("pid", W.DWORD), ("mode", W.DWORD)]

        class Blob(C.Structure):
            _fields_ = [("size", W.DWORD), ("data", C.c_void_p)]

        class Value(C.Union):
            _fields_ = [("blob", Blob), ("storage", C.c_byte * 16)]

        class PropVariant(C.Structure):
            _fields_ = [("vt", W.WORD), ("r1", W.WORD), ("r2", W.WORD),
                        ("r3", W.WORD), ("value", Value)]

        class Operation(COM.IUnknown):
            _iid_ = COM.GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
            _methods_ = [COM.COMMETHOD([], C.HRESULT, "GetActivateResult",
                                      (["out"], C.POINTER(C.HRESULT), "result"),
                                      (["out"], C.POINTER(C.POINTER(COM.IUnknown)), "client"))]

        class Completion(COM.IUnknown):
            _iid_ = COM.GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
            _methods_ = [COM.COMMETHOD([], C.HRESULT, "ActivateCompleted",
                                      (["in"], C.POINTER(Operation), "operation"))]

        class Agile(COM.IUnknown):
            _iid_ = COM.GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
            _methods_ = []

        class CaptureClient(COM.IUnknown):
            _iid_ = COM.GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
            _methods_ = [
                COM.COMMETHOD([], C.HRESULT, "GetBuffer",
                              (["out"], C.POINTER(C.POINTER(C.c_ubyte)), "data"),
                              (["out"], C.POINTER(W.UINT), "frames"),
                              (["out"], C.POINTER(W.DWORD), "flags"),
                              (["out"], C.POINTER(C.c_ulonglong), "position"),
                              (["out"], C.POINTER(C.c_ulonglong), "qpc")),
                COM.COMMETHOD([], C.HRESULT, "ReleaseBuffer", (["in"], W.UINT, "frames")),
                COM.COMMETHOD([], C.HRESULT, "GetNextPacketSize",
                              (["out"], C.POINTER(W.UINT), "frames")),
            ]

        class Handler(COM.COMObject):
            _com_interfaces_ = [Completion, Agile]

            def __init__(self):
                self.ready = Event()
                self.client = None
                self.error = ""

            def ActivateCompleted(self, operation):
                try:
                    result, unknown = operation.GetActivateResult()
                    if result < 0:
                        raise WindowsAudioError(f"Activación WASAPI fallida: 0x{result & 0xffffffff:08X}")
                    self.client = unknown.QueryInterface(IAudioClient)
                except Exception as exc:
                    self.error = str(exc)
                finally:
                    self.ready.set()
                return 0

        self.client = None
        self.capture = None
        self.handle = None
        self.started = False
        self._handler = Handler()
        self._operation = C.POINTER(Operation)()
        self._params = Activation(1, pid, 0)
        self._variant = PropVariant()
        self._variant.vt = 65
        self._variant.value.blob = Blob(C.sizeof(self._params), C.addressof(self._params))
        self.kernel = C.WinDLL("kernel32", use_last_error=True, winmode=0x800)
        self.kernel.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
        self.kernel.CreateEventW.restype = W.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.kernel.WaitForSingleObject.restype = W.DWORD
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.kernel.CloseHandle.restype = W.BOOL
        api = C.WinDLL("Mmdevapi", winmode=0x800)
        activate = api.ActivateAudioInterfaceAsync
        activate.argtypes = [W.LPCWSTR, C.POINTER(COM.GUID), C.POINTER(PropVariant),
                             C.POINTER(Completion), C.POINTER(C.POINTER(Operation))]
        activate.restype = C.c_long
        try:
            result = activate("VAD\\Process_Loopback", C.byref(IAudioClient._iid_),
                              C.byref(self._variant), self._handler.QueryInterface(Completion),
                              C.byref(self._operation))
            if result < 0:
                raise WindowsAudioError(f"La API de audio por aplicación no está disponible: 0x{result & 0xffffffff:08X}")
            deadline = time.monotonic() + timeout
            while not self._handler.ready.wait(0.05):
                if stop_event.is_set() or time.monotonic() >= deadline:
                    raise WindowsAudioError("Se canceló o agotó la espera de audio por aplicación.")
            if self._handler.error:
                raise WindowsAudioError(self._handler.error)
            self.client = self._handler.client
            fmt = WAVEFORMATEX(1, self.channels, self.sample_rate,
                               self.sample_rate * self.channels * 2, self.channels * 2, 16, 0)
            self.client.Initialize(0, 0x20000 | 0x40000 | 0x80000000, 0, 0, C.byref(fmt), None)
            self.capture = self.client.GetService(C.byref(CaptureClient._iid_)).QueryInterface(CaptureClient)
            self.handle = self.kernel.CreateEventW(None, False, False, None)
            if not self.handle:
                raise C.WinError(C.get_last_error())
            self.client.SetEventHandle(self.handle)
            self.client.Start()
            self.started = True
        except BaseException:
            self.close()
            raise

    def read(self) -> bytes:
        if self.kernel.WaitForSingleObject(self.handle, 40) == 0xffffffff:
            raise C.WinError(C.get_last_error())
        parts = []
        size = 0
        while self.capture.GetNextPacketSize():
            pointer, frames, flags, _, _ = self.capture.GetBuffer()
            try:
                if not 0 <= frames <= self.sample_rate * 2:
                    raise WindowsAudioError("Windows entregó un tamaño de audio inválido.")
                length = frames * self.channels * 2
                if flags & 2:
                    data = b"\0" * length
                elif pointer:
                    data = C.string_at(pointer, length)
                else:
                    raise WindowsAudioError("Windows entregó un búfer de audio vacío.")
                size += length
                if size > self.sample_rate * self.channels * 4:
                    raise WindowsAudioError("El lector de audio de la aplicación se retrasó demasiado.")
                parts.append(data)
            finally:
                self.capture.ReleaseBuffer(frames)
        return b"".join(parts)

    def close(self):
        if self.started and self.client is not None:
            try:
                self.client.Stop()
            except Exception:
                pass
            finally:
                self.started = False
        self.capture = None
        self.client = None
        if getattr(self, "_handler", None) is not None:
            self._handler.client = None
        self._operation = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
