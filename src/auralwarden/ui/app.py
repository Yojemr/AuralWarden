from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from auralwarden.paths import application_root
from auralwarden.local_control import TRANSPORT_PROTOCOL_VERSION, transport_proof
from auralwarden.ui.assets import asset_path
from auralwarden.ui.main_window import MainWindow
from auralwarden.ui.styles import APP_STYLESHEET


def configure_application_identity(app: QApplication) -> None:
    app.setApplicationName("AuralWarden")
    app.setApplicationDisplayName("")
    app.setOrganizationName("AuralWarden")


def _load_windows_ui_fonts() -> str:
    fonts_root = Path("C:/Windows/Fonts")
    font_files = (
        "segoeui.ttf",
        "segoeuib.ttf",
        "segoeuil.ttf",
        "segoeuisl.ttf",
        "segoeuii.ttf",
    )
    loaded_family = ""
    for filename in font_files:
        path = fonts_root / filename
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families and not loaded_family:
            loaded_family = families[0]
    return loaded_family or QFontDatabase.systemFont(
        QFontDatabase.SystemFont.GeneralFont
    ).family()


MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CONNECTIONS = 8
REQUEST_DEADLINE_MS = 5_000


def _local_account_session() -> str:
    if os.name != "nt":
        return str(os.getuid())
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "No se pudo identificar la cuenta local.")
    try:
        required = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        data = ctypes.create_string_buffer(required.value)
        if not advapi.GetTokenInformation(token, 1, data, required, ctypes.byref(required)):
            raise OSError(ctypes.get_last_error(), "No se pudo leer la identidad local.")
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError(ctypes.get_last_error(), "No se pudo identificar la cuenta local.")
        try:
            identity = sid_text.value
        finally:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        session = wintypes.DWORD()
        if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise OSError(ctypes.get_last_error(), "No se pudo identificar la sesión local.")
        return f"{identity}:{session.value}"
    finally:
        kernel.CloseHandle(token)


def single_instance_name(root: Path | None = None) -> str:
    location = str((root or application_root()).resolve()).casefold() + "|" + _local_account_session()
    digest = hashlib.sha256(location.encode("utf-8")).hexdigest()[:20]
    return f"Yojemr.AuralWarden.{digest}"


class SingleInstanceGuard:
    def __init__(self, name: str) -> None:
        self.name = name
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.setMaxPendingConnections(MAX_CONNECTIONS)
        self._connections: set[QLocalSocket] = set()

    def claim(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(250):
            probe.write(b"show\n")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            raise RuntimeError(
                "No fue posible comprobar si AuralWarden ya está abierto."
            )
        return True

    def bind(self, window: MainWindow) -> None:
        def process_connections() -> None:
            while self.server.hasPendingConnections():
                connection = self.server.nextPendingConnection()
                if connection is None:
                    continue
                if len(self._connections) >= MAX_CONNECTIONS:
                    connection.abort()
                    connection.deleteLater()
                    continue
                self._bind_connection(connection, window)

        self.server.newConnection.connect(process_connections)

    def _bind_connection(self, connection: QLocalSocket, window: MainWindow) -> None:
        self._connections.add(connection)
        connection.setReadBufferSize(MAX_REQUEST_BYTES + 1)
        raw = bytearray()
        server_nonce = secrets.token_hex(32)
        client_nonce = ""
        token = ""
        stage = "hello"
        timer = QTimer(connection)
        timer.setSingleShot(True)

        def cleanup() -> None:
            timer.stop()
            self._connections.discard(connection)
            connection.deleteLater()

        def respond(response: dict[str, Any], *, finish: bool = False) -> None:
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
            if len(encoded) > MAX_RESPONSE_BYTES:
                encoded = b'{"ok":false,"code":"response_too_large"}\n'
                finish = True
            connection.write(encoded)
            connection.flush()
            if finish:
                connection.disconnectFromServer()

        def read() -> None:
            nonlocal stage, client_nonce, token
            raw.extend(bytes(connection.readAll()))
            if len(raw) > MAX_REQUEST_BYTES:
                respond({"ok": False, "code": "request_too_large"}, finish=True)
                return
            if raw == b"show":
                raw.extend(b"\n")
            while b"\n" in raw:
                line, _, remainder = raw.partition(b"\n")
                raw[:] = remainder
                if stage == "hello" and line == b"show":
                    window._restore_window()
                    connection.disconnectFromServer()
                    return
                try:
                    value = json.loads(line.decode("utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError("La solicitud debe ser un objeto JSON.")
                    if stage == "hello":
                        client_nonce = str(value.get("client_nonce") or "")
                        if (value.get("transport_version") != TRANSPORT_PROTOCOL_VERSION
                                or len(client_nonce) != 64
                                or any(c not in "0123456789abcdef" for c in client_nonce)):
                            raise ValueError("Inicio de autenticación no válido.")
                        if not window.settings.allow_local_control:
                            respond({"ok": False, "code": "local_control_disabled"}, finish=True)
                            return
                        token = window.local_control_credentials.read()
                        if not token:
                            raise ValueError("La credencial local no está disponible.")
                        respond({"type": "server_proof", "proof": transport_proof(
                            token, "server", server_nonce, client_nonce
                        )})
                        stage = "request"
                    elif stage == "request":
                        request = value.get("payload")
                        current_token = window.local_control_credentials.read()
                        if (not isinstance(request, dict) or "token" in request
                                or not current_token or not hmac.compare_digest(current_token, token)
                                or not hmac.compare_digest(str(value.get("proof") or ""),
                                    transport_proof(current_token, "client", server_nonce, client_nonce, request))):
                            respond({"ok": False, "code": "unauthorized"}, finish=True)
                            return
                        stage = "done"
                        respond(window.handle_local_control({**request, "token": current_token}), finish=True)
                        return
                    else:
                        raise ValueError("La conexión ya terminó.")
                except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
                    respond({"ok": False, "code": "invalid_request", "message": str(exc)}, finish=True)
                    return

        connection.readyRead.connect(read)
        connection.disconnected.connect(cleanup)
        timer.timeout.connect(connection.abort)
        timer.start(REQUEST_DEADLINE_MS)
        respond({"type": "challenge", "transport_version": TRANSPORT_PROTOCOL_VERSION,
                 "server_nonce": server_nonce})
        if connection.bytesAvailable():
            read()

    def close(self) -> None:
        for connection in tuple(self._connections):
            connection.abort()
        if self.server.isListening():
            self.server.close()
            QLocalServer.removeServer(self.name)


def send_local_control_request(
    request: dict[str, Any], *, timeout_ms: int = 5_000, server_name: str | None = None
) -> dict[str, Any]:
    socket = QLocalSocket()
    socket.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
    socket.connectToServer(server_name or single_instance_name())
    if not socket.waitForConnected(timeout_ms):
        return {
            "ok": False,
            "code": "application_unavailable",
            "message": "AuralWarden no está abierto en esta carpeta portable.",
        }
    deadline = time.monotonic() + timeout_ms / 1000.0
    buffer = bytearray()

    def receive() -> dict[str, Any]:
        while b"\n" not in buffer:
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0 or (not socket.bytesAvailable() and not socket.waitForReadyRead(remaining)):
                raise TimeoutError("AuralWarden no respondió a tiempo.")
            buffer.extend(bytes(socket.readAll()))
            if len(buffer) > MAX_RESPONSE_BYTES:
                raise ValueError("La respuesta local supera el límite permitido.")
        line, _, rest = buffer.partition(b"\n")
        buffer[:] = rest
        value = json.loads(line.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("La respuesta debe ser un objeto JSON.")
        return value

    def send(value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("La solicitud supera el límite de 64 KiB.")
        socket.write(raw)
        socket.flush()
        if socket.bytesToWrite() and not socket.waitForBytesWritten(
            max(1, int((deadline - time.monotonic()) * 1000))
        ):
            raise TimeoutError("AuralWarden no recibió la solicitud a tiempo.")

    try:
        challenge = receive()
        server_nonce = str(challenge.get("server_nonce") or "")
        if (challenge.get("transport_version") != TRANSPORT_PROTOCOL_VERSION
                or len(server_nonce) != 64
                or any(c not in "0123456789abcdef" for c in server_nonce)):
            raise ValueError("No se pudo autenticar el servidor local.")
        client_nonce = secrets.token_hex(32)
        token = str(request.get("token") or "")
        send({"transport_version": TRANSPORT_PROTOCOL_VERSION, "client_nonce": client_nonce})
        proof = receive()
        if proof.get("code") == "local_control_disabled":
            return proof
        if not token or not hmac.compare_digest(str(proof.get("proof") or ""),
                transport_proof(token, "server", server_nonce, client_nonce)):
            raise ValueError("No se pudo autenticar el servidor local.")
        payload = {key: value for key, value in request.items() if key != "token"}
        send({"payload": payload, "proof": transport_proof(token, "client", server_nonce, client_nonce, payload)})
        return receive()
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError, TimeoutError) as exc:
        return {
            "ok": False,
            "code": "transport_error",
            "message": str(exc),
        }
    finally:
        socket.abort()


def run_app(
    *,
    demo: bool = False,
    screenshot: Path | None = None,
    screenshot_delay_ms: int = 12_000,
) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv)
    configure_application_identity(app)
    app.setWindowIcon(QIcon(str(asset_path("app-icon.ico"))))
    font_family = _load_windows_ui_fonts()
    app.setFont(QFont(font_family, 10))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    instance_guard = SingleInstanceGuard(single_instance_name())
    if not instance_guard.claim():
        return 0
    window = MainWindow(demo=demo)
    instance_guard.bind(window)
    window.show()
    if screenshot is not None:
        destination = screenshot.expanduser().resolve()

        def capture() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(destination), "PNG")
            window._quitting = True
            window.preview.stop()
            window.controller.stop_and_wait()
            window.tray.hide()
            window.hide()
            QTimer.singleShot(0, lambda: app.exit(0))

        QTimer.singleShot(max(1_000, screenshot_delay_ms), capture)
    try:
        return int(app.exec())
    finally:
        instance_guard.close()
