import hashlib
import io
import zipfile

import pytest

from auralwarden.components import ComponentInstallError, ComponentManager, ComponentSpec


def _archive(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_component_installation_verifies_hash_and_executable(tmp_path) -> None:
    payload = _archive({"bin/whisper-cli.exe": b"portable executable"})
    spec = ComponentSpec(
        "test-component",
        "1.0",
        "memory://component",
        hashlib.sha256(payload).hexdigest(),
        ("whisper-cli.exe",),
    )
    manager = ComponentManager(tmp_path / "components")
    installed = manager.install(spec, opener=lambda _url: io.BytesIO(payload))
    assert installed.is_file()
    assert installed.read_bytes() == b"portable executable"


def test_component_installation_rejects_zip_traversal(tmp_path) -> None:
    payload = _archive({"../outside/whisper-cli.exe": b"unsafe"})
    spec = ComponentSpec(
        "unsafe",
        "1.0",
        "memory://unsafe",
        hashlib.sha256(payload).hexdigest(),
        ("whisper-cli.exe",),
    )
    manager = ComponentManager(tmp_path / "components")
    with pytest.raises(ComponentInstallError, match="ruta insegura"):
        manager.install(spec, opener=lambda _url: io.BytesIO(payload))
    assert not (tmp_path / "outside" / "whisper-cli.exe").exists()
