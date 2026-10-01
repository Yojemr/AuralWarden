from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from auralwarden.model_installer import Progress, _check_cancel, _open_download


CUDA_COMPONENT = "cuda-12.9"
CUDA_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
CUDA_PACKAGES = (
    {
        "url": "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
        "size": 553162896,
        "sha256": "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",
        "members": {
            "nvidia/cublas/bin/cublas64_12.dll": "cublas64_12.dll",
            "nvidia/cublas/bin/cublasLt64_12.dll": "cublasLt64_12.dll",
            "nvidia_cublas_cu12-12.9.2.10.dist-info/licenses/License.txt": "NVIDIA-cuBLAS-LICENSE.txt",
        },
    },
    {
        "url": "https://files.pythonhosted.org/packages/c0/82/0a5f7f2b03b4e10aacb3146715724e1b96bb993cc7d199be28c9825aa120/ctranslate2-4.8.1-cp312-cp312-win_amd64.whl",
        "size": 19220789,
        "sha256": "49f96e861b57301f0b76a082109bde2cac8204a6b4fedc870883008271e82251",
        "members": {"ctranslate2/cudnn64_9.dll": "cudnn64_9.dll"},
    },
)


def install_optional_cuda(root: Path, *, cancel: threading.Event, progress: Progress) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / CUDA_COMPONENT
    if target.exists():
        if all((target / name).is_file() for name in CUDA_DLLS):
            return target
        raise FileExistsError("Existe un componente CUDA incompleto; se conserva sin sobrescribir.")
    if shutil.disk_usage(root).free < 1500 * 1024**2:
        raise OSError("CUDA necesita 1,5 GiB libres durante la preparación.")
    total = sum(package["size"] for package in CUDA_PACKAGES)
    completed = 0
    with tempfile.TemporaryDirectory(prefix=".cuda-", dir=root) as temporary:
        staging = Path(temporary)
        for package in CUDA_PACKAGES:
            archive_path = staging / "component.whl"
            digest = hashlib.sha256()
            count = 0
            last = 0.0
            _check_cancel(cancel)
            with _open_download(package["url"]) as response, archive_path.open("xb") as output:
                while True:
                    _check_cancel(cancel)
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > package["size"]:
                        raise ValueError("Componente CUDA demasiado grande.")
                    digest.update(block)
                    output.write(block)
                    if time.monotonic() - last > 0.1:
                        progress(completed + count, total, "Descargando CUDA opcional…")
                        last = time.monotonic()
            if count != package["size"] or digest.hexdigest() != package["sha256"]:
                raise ValueError("El componente CUDA no coincide con su SHA-256.")
            with zipfile.ZipFile(archive_path) as archive:
                for member, name in package["members"].items():
                    info = archive.getinfo(member)
                    if info.file_size > 800 * 1024**2 or Path(name).name != name:
                        raise ValueError("Archivo CUDA fuera de los límites permitidos.")
                    # Extract an explicit member to a fixed basename, never extractall.
                    with archive.open(info) as source, (staging / name).open("xb") as output:
                        while block := source.read(1024 * 1024):
                            _check_cancel(cancel)
                            output.write(block)
            archive_path.unlink()
            completed += count
        _check_cancel(cancel)
        if target.exists():
            raise FileExistsError("Otro instalador creó el componente. Se conserva intacto.")
        staging.rename(target)
    progress(total, total, "CUDA opcional preparado")
    return target
