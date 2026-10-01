import json

from auralwarden.models import SessionState
from auralwarden.runtime_status import RuntimeStatusStore


def test_runtime_status_distinguishes_open_app_from_monitoring(tmp_path) -> None:
    path = tmp_path / "runtime-status.json"
    store = RuntimeStatusStore(path)

    store.write(SessionState.STOPPED, source="https://youtu.be/example")
    stopped = json.loads(path.read_text(encoding="utf-8"))
    assert stopped["application_open"] is True
    assert stopped["monitoring"] is False
    assert stopped["state"] == "stopped"

    store.write(SessionState.RECONNECTING, detail="Intento 2")
    reconnecting = json.loads(path.read_text(encoding="utf-8"))
    assert reconnecting["monitoring"] is True
    assert reconnecting["state"] == "reconnecting"


def test_runtime_status_records_closed_application(tmp_path) -> None:
    path = tmp_path / "runtime-status.json"
    RuntimeStatusStore(path).write(
        SessionState.STOPPED,
        application_open=False,
        detail="AuralWarden se cerró.",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["application_open"] is False
    assert payload["monitoring"] is False
