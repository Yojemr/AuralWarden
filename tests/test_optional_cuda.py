import hashlib
import io
import threading
import zipfile

import pytest

from auralwarden import optional_cuda


def _wheel(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return stream.getvalue()


def test_optional_cuda_extracts_only_fixed_members(tmp_path, monkeypatch):
    wheels = []
    packages = []
    for index, members in enumerate((
        {"pkg/cublas.dll": b"blas", "pkg/cublaslt.dll": b"blaslt", "pkg/LICENSE": b"license", "../escape": b"bad"},
        {"pkg/cudnn.dll": b"dnn"},
    )):
        payload = _wheel(members)
        wheels.append(payload)
        packages.append({
            "url": f"https://example.invalid/{index}.whl",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "members": {name: {"pkg/cublas.dll": "cublas64_12.dll", "pkg/cublaslt.dll": "cublasLt64_12.dll",
                                      "pkg/LICENSE": "NVIDIA-cuBLAS-LICENSE.txt", "pkg/cudnn.dll": "cudnn64_9.dll"}[name]
                        for name in members if name != "../escape"},
        })
    monkeypatch.setattr(optional_cuda, "CUDA_PACKAGES", tuple(packages))
    monkeypatch.setattr(optional_cuda, "_open_download", lambda url: io.BytesIO(wheels[int(url[-5])]))
    target = optional_cuda.install_optional_cuda(tmp_path, cancel=threading.Event(), progress=lambda *_: None)
    assert {item.name for item in target.iterdir()} == {
        "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "NVIDIA-cuBLAS-LICENSE.txt"
    }
    assert not (tmp_path.parent / "escape").exists()


def test_optional_cuda_corruption_is_never_published(tmp_path, monkeypatch):
    package = dict(optional_cuda.CUDA_PACKAGES[0])
    package["size"] = 5
    package["sha256"] = hashlib.sha256(b"valid").hexdigest()
    monkeypatch.setattr(optional_cuda, "CUDA_PACKAGES", (package,))
    monkeypatch.setattr(optional_cuda, "_open_download", lambda _: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError):
        optional_cuda.install_optional_cuda(tmp_path, cancel=threading.Event(), progress=lambda *_: None)
    assert not (tmp_path / optional_cuda.CUDA_COMPONENT).exists()


def test_optional_cuda_existing_incomplete_is_preserved(tmp_path):
    target = tmp_path / optional_cuda.CUDA_COMPONENT
    target.mkdir()
    marker = target / "personal.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        optional_cuda.install_optional_cuda(tmp_path, cancel=threading.Event(), progress=lambda *_: None)
    assert marker.read_text(encoding="utf-8") == "keep"
