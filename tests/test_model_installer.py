import hashlib
import io
import threading
from pathlib import Path

import pytest

from auralwarden import model_installer as installer


@pytest.fixture
def catalog(monkeypatch):
    contents = {"config.json": b"{}", "model.bin": b"verified-model", "tokenizer.json": b"{}"}
    manifest = {"tiny": {"repo": "example/model", "revision": "a" * 40, "files": [
        {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in contents.items()
    ]}}
    monkeypatch.setattr(installer, "model_manifest", lambda: manifest)
    monkeypatch.setattr(installer, "_open_download", lambda url: io.BytesIO(contents[url.rsplit("/", 1)[-1]]))
    return contents


def test_verified_model_is_published_and_reusable(tmp_path, catalog, monkeypatch):
    updates = []
    result = installer.install_whisper_model("tiny", tmp_path, progress=lambda *args: updates.append(args))
    assert (result / "model.bin").read_bytes() == catalog["model.bin"]
    assert not list((tmp_path / ".downloads").iterdir())
    assert updates[-1][0] == updates[-1][1]
    monkeypatch.setattr(installer, "_open_download", lambda _: pytest.fail("Unexpected network request"))
    assert installer.install_whisper_model("tiny", tmp_path) == result


@pytest.mark.parametrize("payload", [b"", b"x" * 200, b"x" * len(b"verified-model")])
def test_invalid_download_never_becomes_visible(tmp_path, catalog, monkeypatch, payload):
    monkeypatch.setattr(installer, "_open_download", lambda _: io.BytesIO(payload))
    with pytest.raises(ValueError):
        installer.install_whisper_model("tiny", tmp_path)
    assert not (tmp_path / "tiny").exists()
    assert not list((tmp_path / ".downloads").iterdir())


def test_cancellation_cleans_only_own_staging(tmp_path, catalog):
    cancel = threading.Event()
    keep = tmp_path / "personal.txt"
    keep.write_text("keep", encoding="utf-8")
    def progress(*_):
        cancel.set()
    with pytest.raises(installer.DownloadCancelled):
        installer.install_whisper_model("tiny", tmp_path, cancel=cancel, progress=progress)
    assert not (tmp_path / "tiny").exists()
    assert keep.read_text() == "keep"
    assert not list((tmp_path / ".downloads").iterdir())


def test_existing_incompatible_model_preserved(tmp_path, catalog):
    (tmp_path / "tiny").mkdir()
    (tmp_path / "tiny" / "model.bin").write_bytes(b"personal model")
    with pytest.raises(FileExistsError):
        installer.install_whisper_model("tiny", tmp_path)
    assert (tmp_path / "tiny" / "model.bin").read_bytes() == b"personal model"


def test_no_space_no_download(tmp_path, catalog, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(OSError):
        installer.install_whisper_model("tiny", tmp_path)
    assert not (tmp_path / "tiny").exists()


def test_unknown_model_and_insecure_scheme_rejected(tmp_path):
    with pytest.raises(ValueError):
        installer.install_whisper_model("../outside", tmp_path)
    with pytest.raises(ValueError):
        installer._open_download("http://example.invalid/model")
    with pytest.raises(ValueError):
        installer._HttpsRedirects().redirect_request(None, None, 302, "", {}, "http://example.invalid")


def test_manifest_is_pinned_and_has_required_files():
    for model in installer.model_manifest().values():
        assert len(model["revision"]) == 40
        files = {f["name"] for f in model["files"]}
        assert {"model.bin", "config.json", "tokenizer.json"} <= files
        for spec in model["files"]:
            assert len(spec["sha256"]) == 64 and spec["size"] > 0
            assert Path(spec["name"]).name == spec["name"]


def test_layout_creation_is_idempotent(tmp_path):
    installer.initialize_data_layout(tmp_path)
    marker = tmp_path / "transcripts" / "personal.txt"
    marker.write_text("keep", encoding="utf-8")
    installer.initialize_data_layout(tmp_path)
    assert marker.read_text() == "keep"
    assert (tmp_path / "runtime" / "components").is_dir()
