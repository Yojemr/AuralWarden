from __future__ import annotations

import json
import os
import time
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from auralwarden.local_control import LocalControlCredentialStore, transport_proof
from auralwarden.ui.app import (SingleInstanceGuard, send_local_control_request,
                               MAX_REQUEST_BYTES, MAX_CONNECTIONS)
from auralwarden.ui.management_dialogs import TranscriptLibraryDialog


@pytest.fixture
def transport(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = LocalControlCredentialStore(tmp_path / "synthetic-credential.json")
    token = store.ensure()
    calls = []
    shown = []
    window = SimpleNamespace(settings=SimpleNamespace(allow_local_control=True),
                             local_control_credentials=store,
                             handle_local_control=lambda request: calls.append(request) or {"ok": True},
                             _restore_window=lambda: shown.append(True))
    guard = SingleInstanceGuard("AuralWarden.Test." + uuid4().hex)
    assert guard.claim()
    guard.bind(window)
    yield app, guard, window, token, calls, shown
    guard.close()
    app.processEvents()


def pump(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def request_in_thread(app, guard, request):
    result = []
    script = (
        "import json,sys; from PySide6.QtCore import QCoreApplication; "
        "app=QCoreApplication([]); from auralwarden.ui.app import send_local_control_request; "
        "request=json.loads(sys.stdin.buffer.read()); "
        "print(json.dumps(send_local_control_request(request, server_name=sys.argv[1], timeout_ms=2000)))"
    )
    process = subprocess.Popen([sys.executable, "-B", "-c", script, guard.name],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def receive():
        output, error = process.communicate(json.dumps(request).encode(), timeout=10)
        result.append(json.loads(output) if output else {"error": error.decode(errors="replace")})
    thread = Thread(target=receive)
    thread.start()
    pump(app, lambda: not thread.is_alive(), timeout=8)
    thread.join()
    return result[0]


def test_transport_authenticates_both_roles_and_keeps_credential_off_wire(transport):
    app, guard, window, token, calls, _ = transport
    response = request_in_thread(app, guard, {"token": token, "action": "status"})
    assert response == {"ok": True}
    assert calls == [{"action": "status", "token": token}]
    assert transport_proof(token, "client", "a", "b") != transport_proof(token, "server", "a", "b")
    assert transport_proof(token, "client", "a", "b", {"action": "status"}) != transport_proof(
        token, "client", "a", "b", {"action": "start"})


def test_disabled_control_preserves_second_instance_show(transport):
    app, guard, window, token, calls, shown = transport
    window.settings.allow_local_control = False
    response = request_in_thread(app, guard, {"token": token, "action": "status"})
    assert response["code"] == "local_control_disabled"
    socket = QLocalSocket()
    socket.connectToServer(guard.name)
    assert socket.waitForConnected(500)
    socket.write(b"show\n")
    socket.flush()
    pump(app, lambda: bool(shown))
    assert calls == []
    socket.abort()


@pytest.mark.parametrize("attack", [b" " * (MAX_REQUEST_BYTES + 1), b"[" * 2000 + b"]" * 2000 + b"\n"],
                         ids=["oversized-whitespace", "deep-json"])
def test_oversized_whitespace_and_deep_json_do_not_dispatch_or_block_gui(transport, attack):
    app, guard, window, token, calls, _ = transport
    ticks = []
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    socket = QLocalSocket()
    socket.connectToServer(guard.name)
    assert socket.waitForConnected(500)
    socket.write(attack)
    socket.flush()
    pump(app, lambda: bool(ticks))
    pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert calls == []
    timer.stop()


def test_incomplete_request_has_absolute_deadline_and_bounded_peers(transport, monkeypatch):
    import auralwarden.ui.app as module
    monkeypatch.setattr(module, "REQUEST_DEADLINE_MS", 60)
    app, guard, window, token, calls, _ = transport
    sockets = []
    try:
        for _ in range(MAX_CONNECTIONS + 2):
            socket = QLocalSocket()
            socket.connectToServer(guard.name)
            socket.waitForConnected(200)
            socket.write(b" ")
            socket.flush()
            sockets.append(socket)
            app.processEvents()
        assert len(guard._connections) <= MAX_CONNECTIONS
        pump(app, lambda: not guard._connections)
        assert calls == []
    finally:
        for socket in sockets:
            socket.abort()


def test_large_legitimate_response_is_not_limited_to_request_size(transport):
    app, guard, window, token, calls, _ = transport
    text = "texto sintetico " * 12000
    window.handle_local_control = lambda request: {"ok": True, "text": text}
    response = request_in_thread(app, guard, {"token": token, "action": "transcript"})
    assert response == {"ok": True, "text": text}


def test_wrong_credential_never_dispatches_request(transport):
    app, guard, window, token, calls, _ = transport
    response = request_in_thread(app, guard, {"token": "wrong synthetic credential", "action": "start"})
    assert not response["ok"]
    assert calls == []


def test_credential_rotation_invalidates_inflight_request(transport):
    app, guard, window, token, calls, _ = transport
    socket = QLocalSocket()
    try:
        socket.connectToServer(guard.name)
        assert socket.waitForConnected(500)
        pump(app, lambda: socket.bytesAvailable() > 0)
        challenge = json.loads(bytes(socket.readAll()))
        client_nonce = "b" * 64
        socket.write(json.dumps({"type": "hello", "transport_version": 2,
                                 "client_nonce": client_nonce}).encode() + b"\n")
        socket.flush()
        pump(app, lambda: socket.bytesAvailable() > 0)
        assert json.loads(bytes(socket.readAll()))["type"] == "server_proof"
        window.local_control_credentials.rotate()
        payload = {"action": "start"}
        socket.write(json.dumps({"type": "request", "payload": payload,
                                 "proof": transport_proof(token, "client", challenge["server_nonce"],
                                                          client_nonce, payload)}).encode() + b"\n")
        socket.flush()
        pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert calls == []
    finally:
        socket.abort()


def test_impersonated_server_receives_no_private_request_or_credential(tmp_path):
    app = QApplication.instance() or QApplication([])
    server = QLocalServer()
    name = "AuralWarden.ImpersonationTest." + uuid4().hex
    assert server.listen(name)
    received = bytearray()
    peers = []
    def connect():
        peer = server.nextPendingConnection()
        peers.append(peer)
        peer.write(json.dumps({"type": "challenge", "transport_version": 2,
                               "server_nonce": "a" * 64}).encode() + b"\n")
        def read():
            received.extend(bytes(peer.readAll()))
            peer.write(b'{"type":"server_proof","proof":"wrong"}\n')
        peer.readyRead.connect(read)
    server.newConnection.connect(connect)
    guard = SimpleNamespace(name=name)
    try:
        response = request_in_thread(app, guard, {"token": "synthetic-secret-do-not-send",
                                                  "action": "set_source", "source": "private-sentinel"})
        assert not response["ok"]
        assert b"synthetic-secret" not in received
        assert b"private-sentinel" not in received
        assert b"set_source" not in received
    finally:
        for peer in peers:
            peer.abort()
        server.close()
        QLocalServer.removeServer(name)


def test_archive_titles_are_literal_plain_text(tmp_path):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "session"
    transcript = folder / "transcripts" / "2026-01-01 - Transcripcion.json"
    transcript.parent.mkdir(parents=True)
    title = '<img src="https://invalid.example/image"><b>Synthetic title</b>'
    (folder / "session.json").write_text(json.dumps({"title": title}), encoding="utf-8")
    transcript.write_text(json.dumps([{"elapsed_seconds": 0, "text": "synthetic"}]), encoding="utf-8")
    dialog = TranscriptLibraryDialog(tmp_path)
    try:
        assert dialog.title_label.textFormat() == Qt.TextFormat.PlainText
        assert dialog.detail_label.textFormat() == Qt.TextFormat.PlainText
        assert dialog.title_label.text() == title
    finally:
        dialog.deleteLater()
        app.processEvents()
