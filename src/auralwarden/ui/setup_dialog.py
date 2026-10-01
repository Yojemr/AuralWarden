from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget, QMessageBox,
)

from auralwarden.diarization.download import download_diarization_models
from auralwarden.hardware import detect_hardware, hardware_summary, select_inference_plan
from auralwarden.model_catalog import resolve_local_whisper_model
from auralwarden.model_installer import DownloadCancelled, install_whisper_model, model_manifest
from auralwarden.models import AppSettings
from auralwarden.paths import data_dir, runtime_executable
from auralwarden.optional_cuda import install_optional_cuda


class SetupWorker(QThread):
    progress = Signal(int, int, str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, settings: AppSettings, root: Path, model: str = "", speakers: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.root = root
        self.model = model
        self.speakers = speakers
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            if self.model == "__cuda__":
                install_optional_cuda(self.root / "runtime" / "components", cancel=self.cancel,
                                      progress=self.progress.emit)
                self.result.emit({"cuda": True})
                return
            if not self.model:
                hardware = detect_hardware()
                plan = select_inference_plan(hardware, performance_mode=self.settings.performance_mode)
                self.result.emit({
                    "recommended": plan.model_candidates[0],
                    "summary": hardware_summary(hardware, plan),
                    "cuda_recommended": hardware.cuda_setup_recommended,
                    "ideal_model": hardware.preferred_cuda_model,
                })
                return
            # Existing discovered models are selected in place, not copied or overwritten.
            local = resolve_local_whisper_model(self.model)
            path = local or install_whisper_model(self.model, self.root / "models",
                                                 cancel=self.cancel, progress=self.progress.emit)
            if self.cancel.is_set():
                raise DownloadCancelled("Preparación cancelada.")
            speaker_paths = None
            if self.speakers:
                speaker_paths = download_diarization_models(self.root / "models" / "diarization",
                                                           cancel=self.cancel, progress=self.progress.emit)
            if self.cancel.is_set():
                raise DownloadCancelled("Preparación cancelada; los modelos ya instalados se conservan.")
            self.result.emit({"model": str(path), "speakers": speaker_paths})
        except DownloadCancelled as exc:
            self.error.emit(str(exc))
        except Exception:
            # Signed redirect URLs and proxy credentials must never reach the dialog/log.
            self.error.emit("No se pudo completar la instalación. Comprueba Internet, espacio libre y permisos de escritura. "
                            "No se sobrescribieron modelos existentes. Puedes reintentar o elegir una carpeta en Preferencias.")


class ModelSetupDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None, *, root: Path | None = None,
                 analyze: bool = True) -> None:
        super().__init__(parent)
        self.settings = settings
        self.root = root or data_dir()
        self.installed_model = ""
        self.speaker_paths: dict | None = None
        self.worker: SetupWorker | None = None
        self._succeeded = False
        self.setWindowTitle("Preparar AuralWarden · Modelos locales")
        self.setMinimumWidth(610)
        layout = QVBoxLayout(self)
        intro = QLabel("El reconocimiento funciona en tu PC. Elige un modelo; solo se descargará al pulsar Preparar. "
                       "No necesitas cuentas ni claves de API. Los modelos existentes se reutilizan.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.hardware = QLabel("Analizando el equipo…" if analyze else "Selecciona un modelo local.")
        self.hardware.setWordWrap(True)
        layout.addWidget(self.hardware)
        self.model = QComboBox()
        for name, info in model_manifest().items():
            mib = sum(f["size"] for f in info["files"]) / 1024**2
            self.model.addItem(f"{name} · {mib:.0f} MiB", name)
        self.model.setToolTip("Tiny/base consumen menos recursos; small/turbo priorizan precisión. La recomendación depende de tu equipo.")
        layout.addWidget(self.model)
        self.speakers = QCheckBox("Preparar también la separación de hablantes (descarga adicional ≈ 50 MiB)")
        self.speakers.setChecked(settings.diarization_enabled)
        self.speakers.setToolTip("Opcional. Separa voces y permite usar perfiles voluntarios; no garantiza identificar correctamente a una persona.")
        layout.addWidget(self.speakers)
        destination = QLabel(f"Datos y nuevas descargas: {self.root}\n"
                             f"FFmpeg: {'incluido / disponible' if runtime_executable('ffmpeg') else 'no disponible; usa el paquete portable completo'}\n"
                             "Modelos Whisper: repositorios verificados de Hugging Face; hablantes: sherpa-onnx / pyannote / 3D-Speaker. "
                             "Ver docs/THIRD_PARTY_NOTICES.md. La descarga comparte tu IP con esos proveedores.")
        destination.setWordWrap(True)
        layout.addWidget(destination)
        self.cuda_button = QPushButton("Preparar CUDA opcional (solo NVIDIA)")
        self.cuda_button.setToolTip("Descarga separada de ≈ 546 MiB; requiere GPU/controlador NVIDIA compatibles y aceptación de sus condiciones. CPU no necesita esto.")
        self.cuda_button.clicked.connect(self._prepare_cuda)
        layout.addWidget(self.cuda_button)
        licenses = QLabel('<a href="https://docs.nvidia.com/cuda/eula/index.html">Condiciones CUDA</a> · '
                          '<a href="https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html">Condiciones cuDNN</a>')
        licenses.setOpenExternalLinks(True)
        layout.addWidget(licenses)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel("Puedes posponer este paso y volver desde Preferencias → Modelos.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.prepare = QPushButton("Preparar")
        self.prepare.setToolTip("Descarga solo archivos faltantes del catálogo fijado y verifica tamaño y SHA-256 antes de usarlos.")
        self.prepare.clicked.connect(self._prepare)
        self.cancel_button = QPushButton("Ahora no")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.prepare)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        if analyze:
            self._start_worker(SetupWorker(settings, self.root, parent=self))

    def _start_worker(self, worker: SetupWorker) -> None:
        self.worker = worker
        self.prepare.setEnabled(False)
        self.model.setEnabled(False)
        self.speakers.setEnabled(False)
        self.cuda_button.setEnabled(False)
        self.cancel_button.setText("Cancelar")
        worker.progress.connect(self._progress)
        worker.result.connect(self._result)
        worker.error.connect(self.status.setText)
        worker.finished.connect(self._finished)
        worker.start()

    def _progress(self, done: int, total: int, detail: str) -> None:
        self.progress.setValue(round(100 * done / max(1, total)))
        self.status.setText(f"{detail} {done / 1024**2:.1f} / {total / 1024**2:.1f} MiB")

    def _prepare(self) -> None:
        if self._succeeded:
            self.accept()
            return
        self.progress.setValue(0)
        self.status.setText("Preparando el modelo…")
        self._start_worker(SetupWorker(self.settings, self.root, str(self.model.currentData()),
                                      self.speakers.isChecked(), self))

    def _prepare_cuda(self) -> None:
        answer = QMessageBox.question(
            self, "CUDA opcional · Condiciones NVIDIA",
            "CPU funciona sin esta descarga. CUDA necesita una GPU NVIDIA y controlador compatible. "
            "Se descargarán bibliotecas de NVIDIA desde PyPI a la carpeta de datos local (≈ 546 MiB; 1,5 GiB libres). "
            "No se instalarán controladores ni se modificará Windows.\n\n"
            "Estas bibliotecas tienen licencias propias, no GPLv3. Revisa los enlaces de condiciones CUDA/cuDNN. "
            "¿Aceptas sus condiciones aplicables y deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_worker(SetupWorker(self.settings, self.root, "__cuda__", parent=self))

    def _result(self, result: dict) -> None:
        if result.get("cuda"):
            self.status.setText("CUDA preparado. Cierra y vuelve a abrir este asistente para actualizar la recomendación del equipo.")
        elif "recommended" in result:
            self.hardware.setText(result["summary"])
            index = self.model.findData(result["recommended"])
            self.model.setCurrentIndex(max(0, index))
            if index >= 0:
                self.model.setItemText(index, self.model.itemText(index) + " · Recomendado")
            if result.get("cuda_recommended"):
                ideal_model = result.get("ideal_model") or "large-v3-turbo"
                self.cuda_button.setText("Preparar CUDA recomendado para esta NVIDIA")
                self.cuda_button.setProperty("accent", True)
                self.cuda_button.style().unpolish(self.cuda_button)
                self.cuda_button.style().polish(self.cuda_button)
                self.status.setText(
                    "Tu GPU NVIDIA puede acelerar notablemente el reconocimiento. "
                    f"Prepara CUDA y después usa {ideal_model}; mientras tanto, "
                    "la recomendación mostrada es la opción CPU disponible."
                )
        else:
            self.installed_model = result["model"]
            self.speaker_paths = result["speakers"]
            self._succeeded = True
            self.progress.setValue(100)
            self.status.setText("Todo listo. El modelo se localizará automáticamente; no hace falta mover carpetas.")

    def _finished(self) -> None:
        self.prepare.setEnabled(True)
        self.prepare.setText("Usar este modelo" if self._succeeded else "Preparar / Reintentar")
        self.model.setEnabled(not self._succeeded)
        self.speakers.setEnabled(not self._succeeded)
        self.cuda_button.setEnabled(not self._succeeded)
        self.cancel_button.setText("Cerrar")
        if self.worker:
            self.worker.deleteLater()
        self.worker = None

    def reject(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.status.setText("Cancelando… La conexión puede tardar hasta 15 segundos en responder.")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
