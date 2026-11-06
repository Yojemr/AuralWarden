from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox

from auralwarden.audio_routing import list_virtual_outputs
from auralwarden.virtual_audio_install import (
    prepare_vb_cable, launch_vb_cable_installer, snapshot_audio_defaults,
    save_install_defaults, recover_install_defaults,
)


class CableDownloadWorker(QThread):
    ready = Signal(object)
    error = Signal(str)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        try:
            self.ready.emit(prepare_vb_cable(self.root))
        except Exception:
            self.error.emit("No se pudo preparar VB-CABLE. Comprueba Internet y el espacio disponible; no se instaló ningún controlador.")


class VirtualAudioDialog(QDialog):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.worker = None
        self.defaults = None
        self.setWindowTitle("Preparar separación de audio")
        self.setMinimumSize(620, 320)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "VB-CABLE estándar crea un único cable virtual para enviar allí la aplicación vigilada "
            "mientras las demás siguen en tus altavoces. No instala Voicemeeter ni cables adicionales.\n\n"
            "Componente de VB-Audio, donationware: https://vb-audio.com/Cable/\n"
            "Descarga aproximada: 1,29 MB. Se conserva el paquete original y se comprueba su integridad. "
            "La instalación requiere administrador y puede solicitar reiniciar Windows. "
            "AuralWarden no reinicia el equipo. El controlador permanece instalado al cerrar la aplicación."
        )
        intro.setTextFormat(Qt.TextFormat.PlainText)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.install_button = QPushButton("Descargar y abrir instalador")
        self.install_button.setToolTip("Instala únicamente VB-CABLE estándar de 64 bits, con autorización de administrador.")
        self.install_button.clicked.connect(self.install)
        buttons.addWidget(self.install_button)
        refresh = QPushButton("Comprobar instalación")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            outputs = list_virtual_outputs()
            if outputs:
                recover_install_defaults(self.root)
                self.defaults = None
                self.timer.stop()
            self.status.setText("VB-CABLE está disponible. Ya puedes iniciar el monitoreo y pulsar Separar audio."
                                if outputs else "VB-CABLE no está disponible todavía. Si acabas de instalarlo, puede requerir reiniciar Windows.")
            self.install_button.setEnabled(not outputs and not (self.worker and self.worker.isRunning()))
        except Exception as exc:
            self.status.setText(f"No se pudo comprobar el cable: {exc}")

    def install(self):
        if QMessageBox.question(self, "Instalar componente opcional",
            "Se abrirá el instalador oficial de VB-CABLE estándar. Requiere administrador y puede pedir reiniciar. "
            "No se instalarán otros productos. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.defaults = snapshot_audio_defaults()
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo conservar la configuración de audio", str(exc))
            return
        self.worker = CableDownloadWorker(self.root / "runtime" / "components", self)
        self.worker.ready.connect(self.open_installer)
        self.worker.error.connect(self.status.setText)
        self.worker.finished.connect(self.refresh)
        self.install_button.setEnabled(False)
        self.status.setText("Preparando el paquete oficial de VB-CABLE…")
        self.worker.start()

    def open_installer(self, executable):
        try:
            self.defaults = snapshot_audio_defaults()
            save_install_defaults(self.root, self.defaults)
            launch_vb_cable_installer(executable)
            self.status.setText("Completa el instalador oficial. No reinicies hasta guardar tu trabajo.")
            self.timer.start()
        except Exception as exc:
            (self.root / "virtual-audio-install-state.json").unlink(missing_ok=True)
            self.status.setText(str(exc))

    def done(self, result):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Espera a que termine la preparación antes de cerrar.")
            return
        self.refresh()
        super().done(result)
