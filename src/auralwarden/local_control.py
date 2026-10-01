from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


CONTROL_PROTOCOL_VERSION = 1
TRANSPORT_PROTOCOL_VERSION = 2
MAX_AUDIT_RECORDS = 500
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def transport_proof(token: str, role: str, server_nonce: str, client_nonce: str,
                    payload: dict[str, Any] | None = None) -> str:
    message = json.dumps(
        [TRANSPORT_PROTOCOL_VERSION, role, server_nonce, client_nonce, payload],
        ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def redact_source(value: str) -> str:
    """Return a useful source label without credentials, query strings or fragments."""

    source = str(value or "").strip()
    if not source:
        return ""
    if source.startswith(("system_audio://", "microphone://", "demo://")):
        return source.split("?", 1)[0].split("#", 1)[0]
    try:
        parsed = urlsplit(source)
    except ValueError:
        return "Fuente local"
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port:
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return "Archivo local" if Path(source).suffix else "Fuente local"


def redact_text(value: object) -> str:
    """Remove URL credentials and query parameters from diagnostic prose."""

    text = str(value or "")
    return _URL_PATTERN.sub(lambda match: redact_source(match.group(0)), text)


class LocalControlCredentialStore:
    """Stores a random, app-specific credential; never an external API key."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure(self) -> str:
        token = self.read()
        return token or self.rotate()

    def rotate(self) -> str:
        token = secrets.token_urlsafe(32)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protocol_version": CONTROL_PROTOCOL_VERSION,
                    "token": token,
                    "created_at": datetime.now().astimezone().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return token

    def read(self) -> str:
        if not self.path.is_file():
            return ""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ""
        return str(payload.get("token") or "") if isinstance(payload, dict) else ""

    def authorize(self, candidate: object) -> bool:
        expected = self.read()
        supplied = str(candidate or "")
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

    def revoke(self) -> None:
        self.path.unlink(missing_ok=True)


class LocalControlAuditStore:
    """Keeps bounded command metadata without arguments, transcript text or tokens."""

    def __init__(self, path: Path, max_records: int = MAX_AUDIT_RECORDS) -> None:
        self.path = path
        self.max_records = max(20, int(max_records))

    def add(self, action: str, *, accepted: bool, code: str) -> None:
        records = self.records()
        records.insert(
            0,
            {
                "occurred_at": datetime.now().astimezone().isoformat(),
                "action": str(action or "unknown")[:64],
                "accepted": bool(accepted),
                "code": str(code or "unknown")[:64],
            },
        )
        self._write(records[: self.max_records])

    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        rows = payload.get("records", []) if isinstance(payload, dict) else []
        return [dict(item) for item in rows if isinstance(item, dict)]

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": 1, "records": records},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def request_fingerprint(request: dict[str, Any]) -> str:
    """Stable non-secret identifier useful when diagnosing a failed request."""

    safe = {
        "protocol_version": request.get("protocol_version"),
        "action": request.get("action"),
    }
    serialized = json.dumps(safe, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()[:12]
