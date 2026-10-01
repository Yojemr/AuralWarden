import hashlib
import io

import pytest

from auralwarden.diarization import download


@pytest.mark.parametrize("payload,limit", [(b"altered", 20), (b"valid" * 20, 10), (b"", 20)])
def test_model_download_rejects_invalid_data_without_replacing_existing(tmp_path, monkeypatch, payload, limit):
    target = tmp_path / "model.onnx"
    target.write_bytes(b"existing valid model")
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(RuntimeError):
        download._download("https://models.example/model", target,
                           sha256=hashlib.sha256(b"valid").hexdigest(), max_bytes=limit)
    assert target.read_bytes() == b"existing valid model"
    assert not target.with_suffix(".onnx.part").exists()


def test_verified_model_download_replaces_atomically(tmp_path, monkeypatch):
    payload = b"verified model data"
    target = tmp_path / "model.onnx"
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    download._download("https://models.example/model", target,
                       sha256=hashlib.sha256(payload).hexdigest(), max_bytes=len(payload))
    assert target.read_bytes() == payload
    assert not target.with_suffix(".onnx.part").exists()
