from __future__ import annotations

from pathlib import Path

from auralwarden.cuda import cuda_runtime_ready, find_nvidia_bin_directories


def test_find_nvidia_bin_directories(tmp_path: Path) -> None:
    cublas = tmp_path / "cublas" / "bin"
    cudnn = tmp_path / "cudnn" / "bin"
    empty = tmp_path / "cuda_nvrtc" / "bin"
    cublas.mkdir(parents=True)
    cudnn.mkdir(parents=True)
    empty.mkdir(parents=True)
    (cublas / "cublas64_12.dll").write_bytes(b"dll")
    (cublas / "cublasLt64_12.dll").write_bytes(b"dll")
    (cudnn / "cudnn64_9.dll").write_bytes(b"dll")

    assert find_nvidia_bin_directories([tmp_path]) == [
        cublas.resolve(),
        cudnn.resolve(),
    ]
    assert not cuda_runtime_ready([cudnn])
    assert cuda_runtime_ready([cublas, cudnn])
