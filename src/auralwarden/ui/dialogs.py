from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from auralwarden.models import AppSettings
from auralwarden.components import ComponentManager, WHISPER_CPP_CPU
from auralwarden.hardware import detect_hardware, hardware_summary, select_inference_plan
from auralwarden.model_catalog import (
    LocalWhisperModel,
    discover_local_whisper_models,
    is_whisper_model_directory,
    resolve_local_whisper_model,
)
from auralwarden.ui.widgets import aw_icon, speaker_color
from auralwarden.ui.setup_dialog import ModelSetupDialog


class PreferencesDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._installation_settings = settings
        self.setWindowTitle("Preferencias de AuralWarden")
        self.setMinimumSize(720, 660)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        recognition = QWidget()
        recognition_form = QFormLayout(recognition)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_browse = QPushButton("Examinar")
        model_browse.setIcon(aw_icon("fa6s.folder-open"))
        model_browse.setToolTip("Seleccionar manualmente una carpeta de modelo Whisper")
        model_browse.clicked.connect(self._browse_model)
        model_row.addWidget(model_browse)
        model_refresh = QPushButton("Detectar")
        model_refresh.setIcon(aw_icon("fa6s.rotate"))
        model_refresh.setToolTip(
            "Buscar otra vez modelos válidos en las carpetas locales conocidas"
        )
        model_refresh.clicked.connect(lambda: self._refresh_models())
        model_row.addWidget(model_refresh)
        recognition_form.addRow("Modelo Whisper", model_row)
        self.install_models = QPushButton("Modelos · Descargar / preparar")
        self.install_models.setToolTip("Asistente local con recomendación para tu equipo, progreso y cancelación. No requiere cuenta ni clave de API.")
        self.install_models.clicked.connect(self._install_models)
        recognition_form.addRow("Preparación", self.install_models)
        self.model_status = QLabel()
        self.model_status.setWordWrap(True)
        self.model_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        recognition_form.addRow("Estado", self.model_status)
        self._models: list[LocalWhisperModel] = []
        self._refresh_models(settings.model_name)
        self.model.currentIndexChanged.connect(self._update_model_status)
        if self.model.lineEdit() is not None:
            self.model.lineEdit().textEdited.connect(self._update_model_status)
        self.language = QComboBox()
        self.language.addItem("Español", "es")
        self.language.addItem("Inglés", "en")
        index = self.language.findData(settings.language)
        self.language.setCurrentIndex(max(0, index))
        recognition_form.addRow("Idioma", self.language)
        self.performance_mode = QComboBox()
        self.performance_mode.addItem("Automático (recomendado)", "auto")
        self.performance_mode.addItem("Precisión máxima", "precision")
        self.performance_mode.addItem("Equilibrado", "balanced")
        self.performance_mode.addItem("Bajo consumo", "low_power")
        mode_index = self.performance_mode.findData(settings.performance_mode)
        self.performance_mode.setCurrentIndex(max(0, mode_index))
        recognition_form.addRow("Rendimiento", self.performance_mode)
        self.backend = QComboBox()
        self.backend.addItem("Automático", "auto")
        self.backend.addItem("faster-whisper", "faster_whisper")
        self.backend.addItem("whisper.cpp / Vulkan", "whisper_cpp")
        backend_index = self.backend.findData(settings.inference_backend)
        self.backend.setCurrentIndex(max(0, backend_index))
        recognition_form.addRow("Motor", self.backend)
        self.device = QComboBox()
        self.device.addItem("Automático", "auto")
        self.device.addItem("NVIDIA CUDA", "cuda")
        self.device.addItem("Procesador (CPU)", "cpu")
        device_index = self.device.findData(settings.inference_device)
        self.device.setCurrentIndex(max(0, device_index))
        recognition_form.addRow("Dispositivo", self.device)
        self.compute_type = QComboBox()
        self.compute_type.addItem("Automática", "auto")
        for value in ("float16", "int8_float16", "int8", "float32"):
            self.compute_type.addItem(value, value)
        compute_index = self.compute_type.findData(settings.compute_type)
        self.compute_type.setCurrentIndex(max(0, compute_index))
        recognition_form.addRow("Precisión", self.compute_type)
        self.hardware_panel = QWidget()
        hardware_row = QHBoxLayout(self.hardware_panel)
        hardware_row.setContentsMargins(0, 0, 0, 0)
        hardware_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.hardware_status = QLabel("Pulsa Analizar para ver la configuración recomendada.")
        self.hardware_status.setWordWrap(True)
        self.hardware_status.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.hardware_status.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        hardware_height = max(76, self.hardware_status.fontMetrics().lineSpacing() * 5)
        self.hardware_status.setMinimumHeight(hardware_height)
        self.hardware_panel.setMinimumHeight(hardware_height)
        self.hardware_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        hardware_row.addWidget(self.hardware_status, 1)
        self.analyze_hardware = QPushButton("Analizar")
        self.analyze_hardware.setIcon(aw_icon("fa6s.microchip"))
        self.analyze_hardware.clicked.connect(self._analyze_hardware)
        hardware_row.addWidget(self.analyze_hardware)
        recognition_form.addRow("Equipo", self.hardware_panel)
        self.window = QDoubleSpinBox()
        self.window.setRange(3.0, 20.0)
        self.window.setSingleStep(0.5)
        self.window.setSuffix(" s")
        self.window.setValue(settings.transcription_window_seconds)
        recognition_form.addRow("Ventana", self.window)
        self.overlap = QDoubleSpinBox()
        self.overlap.setRange(0.0, 5.0)
        self.overlap.setSingleStep(0.5)
        self.overlap.setSuffix(" s")
        self.overlap.setValue(settings.transcription_overlap_seconds)
        recognition_form.addRow("Solapamiento", self.overlap)
        self.low_confidence = QDoubleSpinBox()
        self.low_confidence.setRange(0.0, 1.0)
        self.low_confidence.setSingleStep(0.01)
        self.low_confidence.setValue(settings.low_confidence_second_pass_threshold)
        recognition_form.addRow("Segunda pasada bajo", self.low_confidence)
        self.context = QTextEdit(settings.recognition_context)
        self.context.setMaximumHeight(80)
        self.context.setPlaceholderText("Tema, canal, nombres o contexto probable")
        recognition_form.addRow("Contexto", self.context)
        self.vocabulary = QLineEdit(", ".join(settings.vocabulary))
        self.vocabulary.setPlaceholderText("Nombres y términos, separados por comas")
        recognition_form.addRow("Vocabulario", self.vocabulary)
        tabs.addTab(recognition, "Reconocimiento")

        behavior = QWidget()
        behavior_form = QFormLayout(behavior)
        self.preview_mode = QComboBox()
        self.preview_mode.addItem("Sincronizada con el texto", "synced")
        self.preview_mode.addItem("Menor latencia", "live")
        preview_index = self.preview_mode.findData(settings.preview_mode)
        self.preview_mode.setCurrentIndex(max(0, preview_index))
        behavior_form.addRow("Vista previa", self.preview_mode)
        self.audio_buffer = QSpinBox()
        self.audio_buffer.setRange(30, 120)
        self.audio_buffer.setSuffix(" s")
        self.audio_buffer.setValue(settings.audio_buffer_seconds)
        behavior_form.addRow("Búfer de audio", self.audio_buffer)
        self.video_buffer = QSpinBox()
        self.video_buffer.setRange(30, 300)
        self.video_buffer.setSuffix(" s")
        self.video_buffer.setValue(settings.video_buffer_seconds)
        behavior_form.addRow("Búfer temporal de vídeo", self.video_buffer)
        self.merge_nearby = QSpinBox()
        self.merge_nearby.setRange(0, 120)
        self.merge_nearby.setSuffix(" s")
        self.merge_nearby.setValue(settings.merge_nearby_seconds)
        behavior_form.addRow("Fusionar alertas cercanas", self.merge_nearby)
        self.auto_save = QCheckBox("Guardar automáticamente al detener")
        self.auto_save.setChecked(settings.auto_save_transcript)
        behavior_form.addRow("Transcripción", self.auto_save)
        self.minimize_to_tray = QCheckBox(
            "Ocultar en la bandeja y continuar monitoreando"
        )
        self.minimize_to_tray.setChecked(settings.minimize_to_tray)
        behavior_form.addRow("Bandeja", self.minimize_to_tray)
        self.dynamic_load_adaptation = QCheckBox(
            "Ajustar el trabajo ante carga sostenida"
        )
        self.dynamic_load_adaptation.setChecked(settings.dynamic_load_adaptation)
        behavior_form.addRow("Recursos", self.dynamic_load_adaptation)
        self.interface_scale = QComboBox()
        for label, value in (
            ("Compacta · 90 %", 90),
            ("Normal · 100 %", 100),
            ("Grande · 110 %", 110),
            ("Muy grande · 125 %", 125),
        ):
            self.interface_scale.addItem(label, value)
        scale_index = self.interface_scale.findData(settings.interface_scale_percent)
        self.interface_scale.setCurrentIndex(max(0, scale_index))
        behavior_form.addRow("Tamaño de interfaz", self.interface_scale)
        self.allow_local_control = QCheckBox(
            "Permitir órdenes locales de agentes y automatizaciones"
        )
        self.allow_local_control.setChecked(settings.allow_local_control)
        behavior_form.addRow("Control externo", self.allow_local_control)
        self.reconnect_enabled = QCheckBox(
            "Esperar y reconectar automáticamente"
        )
        self.reconnect_enabled.setChecked(settings.reconnect_enabled)
        behavior_form.addRow("Conexión del directo", self.reconnect_enabled)
        self.reconnect_attempts = QSpinBox()
        self.reconnect_attempts.setRange(0, 50)
        self.reconnect_attempts.setSpecialValueText("Sin límite")
        self.reconnect_attempts.setValue(settings.reconnect_max_attempts)
        behavior_form.addRow("Máximo de intentos", self.reconnect_attempts)
        self.reconnect_initial_delay = QSpinBox()
        self.reconnect_initial_delay.setRange(1, 120)
        self.reconnect_initial_delay.setSuffix(" s")
        self.reconnect_initial_delay.setValue(settings.reconnect_initial_delay_seconds)
        behavior_form.addRow("Primera espera", self.reconnect_initial_delay)
        self.reconnect_max_delay = QSpinBox()
        self.reconnect_max_delay.setRange(5, 600)
        self.reconnect_max_delay.setSuffix(" s")
        self.reconnect_max_delay.setValue(settings.reconnect_max_delay_seconds)
        behavior_form.addRow("Espera máxima", self.reconnect_max_delay)
        tabs.addTab(behavior, "Comportamiento")

        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        diarization_root = ""
        if settings.diarization_segmentation_model:
            diarization_root = str(Path(settings.diarization_segmentation_model).parent)
        self.diarization_root = QLineEdit(diarization_root)
        diarization_row = QHBoxLayout()
        diarization_row.addWidget(self.diarization_root, 1)
        diarization_browse = QPushButton("Examinar")
        diarization_browse.setIcon(aw_icon("fa6s.folder-open"))
        diarization_browse.setToolTip(
            "Seleccionar la carpeta que contiene segmentation.onnx y embedding.onnx"
        )
        diarization_browse.clicked.connect(self._browse_diarization)
        diarization_row.addWidget(diarization_browse)
        advanced_form.addRow("Modelos de hablantes", diarization_row)
        self.cluster_threshold = QDoubleSpinBox()
        self.cluster_threshold.setRange(0.30, 0.95)
        self.cluster_threshold.setSingleStep(0.01)
        self.cluster_threshold.setValue(settings.diarization_cluster_threshold)
        advanced_form.addRow("Umbral de agrupación", self.cluster_threshold)
        self.speaker_threshold = QDoubleSpinBox()
        self.speaker_threshold.setRange(0.15, 0.90)
        self.speaker_threshold.setSingleStep(0.01)
        self.speaker_threshold.setValue(settings.speaker_match_threshold)
        advanced_form.addRow("Persistencia de hablante", self.speaker_threshold)
        self.voice_profile_threshold = QDoubleSpinBox()
        self.voice_profile_threshold.setRange(0.30, 0.95)
        self.voice_profile_threshold.setSingleStep(0.01)
        self.voice_profile_threshold.setValue(settings.voice_profile_threshold)
        advanced_form.addRow("Reconocimiento de perfil", self.voice_profile_threshold)
        self.diarization_threads = QSpinBox()
        self.diarization_threads.setRange(1, 8)
        self.diarization_threads.setValue(settings.diarization_threads)
        advanced_form.addRow("Hilos de diarización", self.diarization_threads)
        self.whisper_cpp_executable = QLineEdit(settings.whisper_cpp_executable)
        cpp_executable_row = QHBoxLayout()
        cpp_executable_row.addWidget(self.whisper_cpp_executable, 1)
        cpp_executable_browse = QPushButton("Examinar")
        cpp_executable_browse.clicked.connect(self._browse_whisper_cpp_executable)
        cpp_executable_row.addWidget(cpp_executable_browse)
        self.install_whisper_cpp = QPushButton("Instalar CPU")
        self.install_whisper_cpp.clicked.connect(self._install_whisper_cpp_cpu)
        cpp_executable_row.addWidget(self.install_whisper_cpp)
        advanced_form.addRow("Componente whisper.cpp", cpp_executable_row)
        self.whisper_cpp_model = QLineEdit(settings.whisper_cpp_model)
        cpp_model_row = QHBoxLayout()
        cpp_model_row.addWidget(self.whisper_cpp_model, 1)
        cpp_model_browse = QPushButton("Examinar")
        cpp_model_browse.clicked.connect(self._browse_whisper_cpp_model)
        cpp_model_row.addWidget(cpp_model_browse)
        advanced_form.addRow("Modelo GGML/GGUF", cpp_model_row)
        self.whisper_cpp_acceleration = QComboBox()
        self.whisper_cpp_acceleration.addItem("Detectar por el componente", "auto")
        self.whisper_cpp_acceleration.addItem("Procesador (CPU)", "cpu")
        self.whisper_cpp_acceleration.addItem("Vulkan (AMD/Intel/NVIDIA)", "vulkan")
        cpp_acceleration_index = self.whisper_cpp_acceleration.findData(
            settings.whisper_cpp_acceleration
        )
        self.whisper_cpp_acceleration.setCurrentIndex(max(0, cpp_acceleration_index))
        advanced_form.addRow("Aceleración whisper.cpp", self.whisper_cpp_acceleration)
        tabs.addTab(advanced, "Avanzado")

        tooltips = {
            self.model: (
                "Automático selecciona el mejor modelo local disponible para la capacidad del equipo."
            ),
            self.language: "Idioma principal esperado en la transmisión.",
            self.performance_mode: (
                "Automático equilibra precisión y velocidad; Bajo consumo reduce modelo, hilos y segundas pasadas."
            ),
            self.backend: (
                "Automático elige el motor compatible. whisper.cpp permite componentes opcionales para CPU o Vulkan."
            ),
            self.device: (
                "Automático usa NVIDIA CUDA cuando está disponible y vuelve a CPU si no hay aceleración compatible."
            ),
            self.compute_type: (
                "Automática elige una precisión segura según el dispositivo y la memoria disponible."
            ),
            self.hardware_status: "Resumen local del equipo y del motor recomendado.",
            self.analyze_hardware: "Detectar procesador, memoria y aceleradores sin enviar datos.",
            self.window: (
                "Duración de cada bloque analizado. Bloques cortos reducen latencia; bloques largos aportan más contexto."
            ),
            self.overlap: (
                "Audio repetido entre bloques para evitar perder palabras en los límites. Aumentarlo consume más procesamiento."
            ),
            self.low_confidence: (
                "Confianza por debajo de la cual AuralWarden intenta una segunda transcripción más precisa."
            ),
            self.context: (
                "Descripción del tema, canal o situación para ayudar a Whisper a interpretar el vocabulario."
            ),
            self.vocabulary: (
                "Nombres propios y términos difíciles que Whisper debe considerar; no generan alertas por sí solos."
            ),
            self.preview_mode: (
                "Sincronizada acompaña el texto; menor latencia muestra imágenes más recientes. La vista se activa manualmente."
            ),
            self.audio_buffer: (
                "Segundos recientes conservados en RAM para construir clips de audio anteriores a una alerta."
            ),
            self.video_buffer: (
                "Segundos recientes de vídeo conservados temporalmente para crear clips MP4."
            ),
            self.merge_nearby: (
                "Une detecciones repetidas de la misma hotword dentro de este intervalo."
            ),
            self.auto_save: (
                "Guarda TXT y JSON automáticamente cuando finaliza correctamente una sesión."
            ),
            self.minimize_to_tray: (
                "Mantiene el monitoreo activo al ocultar la ventana en la bandeja de Windows."
            ),
            self.dynamic_load_adaptation: (
                "Observa CPU, GPU, RAM y VRAM durante varios segundos. Reduce el trabajo secundario bajo carga y vuelve gradualmente al modo normal."
            ),
            self.interface_scale: (
                "Compacta ayuda en pantallas pequeñas; los tamaños grandes mejoran la legibilidad. Se aplica al guardar."
            ),
            self.allow_local_control: (
                "Permite consultar el estado y la transcripción, cambiar enlaces y hotwords, e iniciar o detener mediante el protocolo local documentado. No abre puertos de red ni acepta órdenes arbitrarias."
            ),
            self.reconnect_enabled: (
                "Si el directo aún no comienza o la conexión se corta, AuralWarden vuelve a intentarlo sin perder la sesión."
            ),
            self.reconnect_attempts: (
                "Número de intentos antes de pedir atención. Cero mantiene la espera hasta que pulses Detener."
            ),
            self.reconnect_initial_delay: (
                "Tiempo antes del primer reintento; las esperas posteriores aumentan progresivamente."
            ),
            self.reconnect_max_delay: (
                "Límite de la espera progresiva entre intentos para no abandonar el directo durante cortes largos."
            ),
            self.diarization_root: (
                "Carpeta de los modelos locales utilizados para separar hablantes."
            ),
            self.cluster_threshold: (
                "Controla cuándo dos voces se consideran la misma persona dentro de una ventana."
            ),
            self.speaker_threshold: (
                "Similitud mínima para conservar una identidad entre ventanas. Un valor menor tolera más variaciones y evita Speakers duplicados."
            ),
            self.voice_profile_threshold: (
                "Similitud mínima para identificar una voz guardada en sesiones futuras. "
                "Un valor mayor reduce confusiones entre personas parecidas."
            ),
            self.diarization_threads: (
                "Hilos de CPU reservados para separar hablantes. Más hilos pueden competir con otras aplicaciones."
            ),
            self.whisper_cpp_executable: (
                "Ejecutable opcional de whisper.cpp. Permite ampliar los motores sin reemplazar la aplicación."
            ),
            self.install_whisper_cpp: (
                "Descarga el componente CPU oficial, comprueba su firma y lo instala dentro de los datos locales."
            ),
            self.whisper_cpp_model: (
                "Modelo GGML/GGUF compatible con whisper.cpp; es independiente de los modelos de faster-whisper."
            ),
            self.whisper_cpp_acceleration: (
                "Selecciona Vulkan únicamente si el ejecutable de whisper.cpp fue compilado con ese soporte."
            ),
        }
        for field, tooltip in tooltips.items():
            field.setToolTip(tooltip)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_model(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Carpeta del modelo Whisper")
        if not selected:
            return
        path = Path(selected)
        if not is_whisper_model_directory(path):
            QMessageBox.warning(
                self,
                "Carpeta de modelo no válida",
                "La carpeta debe contener config.json, model.bin y tokenizer.json.",
            )
            return
        resolved = str(path.resolve())
        index = self.model.findData(resolved)
        if index < 0:
            self.model.addItem(f"{path.name} · carpeta seleccionada", resolved)
            index = self.model.count() - 1
        self.model.setCurrentIndex(index)
        self._update_model_status()

    def _install_models(self) -> None:
        dialog = ModelSetupDialog(self._installation_settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._refresh_models(dialog.installed_model)
        if dialog.speaker_paths:
            self.diarization_root.setText(str(dialog.speaker_paths["segmentation"].parent))

    def _refresh_models(self, preferred: str | None = None) -> None:
        current = preferred or self._selected_model_value()
        self._models = discover_local_whisper_models()
        resolved = resolve_local_whisper_model(current, self._models)
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItem("Automático (recomendado)", "auto")
        for model in self._models:
            self.model.addItem(f"{model.name} · local", str(model.path))
        if current.strip().casefold() in {"", "auto", "automatic", "automatico"}:
            self.model.setCurrentIndex(0)
        elif resolved is not None:
            index = self.model.findData(str(resolved))
            self.model.setCurrentIndex(max(0, index))
        else:
            self.model.setCurrentIndex(-1)
            self.model.setEditText(current or "large-v3-turbo")
        self.model.blockSignals(False)
        self._update_model_status()

    def _selected_model_value(self) -> str:
        data = self.model.currentData()
        if data:
            return str(data)
        return self.model.currentText().strip()

    def _update_model_status(self, *_: object) -> None:
        if self._selected_model_value() == "auto":
            if self._models:
                self.model_status.setText(
                    f"Selección automática activa · {len(self._models)} modelo(s) local(es) detectado(s)."
                )
                self.model_status.setStyleSheet("color:#48d7aa;")
            else:
                self.model_status.setText(
                    "Selección automática activa, pero todavía no hay modelos locales."
                )
                self.model_status.setStyleSheet("color:#f0ac24;")
            return
        resolved = resolve_local_whisper_model(
            self._selected_model_value(), self._models
        )
        if resolved is None:
            self.model_status.setText(
                "No encontrado. Pulsa Detectar o Examinar para seleccionar una carpeta."
            )
            self.model_status.setStyleSheet("color:#f0ac24;")
            return
        self.model_status.setText(f"Detectado automáticamente: {resolved}")
        self.model_status.setStyleSheet("color:#48d7aa;")

    def _browse_diarization(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Carpeta de modelos de diarización"
        )
        if selected:
            self.diarization_root.setText(selected)

    def _browse_whisper_cpp_executable(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Ejecutable de whisper.cpp", "", "Ejecutable (whisper-cli.exe main.exe);;Todos (*)"
        )
        if selected:
            self.whisper_cpp_executable.setText(selected)

    def _browse_whisper_cpp_model(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Modelo de whisper.cpp", "", "Modelos Whisper (*.bin *.gguf);;Todos (*)"
        )
        if selected:
            self.whisper_cpp_model.setText(selected)

    def _install_whisper_cpp_cpu(self) -> None:
        manager = ComponentManager()
        existing = manager.find_executable(WHISPER_CPP_CPU)
        if existing is not None:
            self.whisper_cpp_executable.setText(str(existing))
            QMessageBox.information(
                self,
                "Componente disponible",
                "whisper.cpp CPU ya está instalado y fue seleccionado.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Instalar componente local",
            "Se descargará el componente oficial whisper.cpp CPU (aprox. 8 MB), "
            "se verificará su firma y se guardará dentro de AuralWarden. El modelo "
            "GGML/GGUF se selecciona por separado. ¿Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.install_whisper_cpp.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            installed = manager.install(WHISPER_CPP_CPU)
            self.whisper_cpp_executable.setText(str(installed))
            index = self.whisper_cpp_acceleration.findData("cpu")
            self.whisper_cpp_acceleration.setCurrentIndex(max(0, index))
            QMessageBox.information(
                self,
                "Instalación completada",
                "El componente CPU quedó instalado y seleccionado.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "No se pudo instalar",
                f"AuralWarden no modificó la configuración. Detalle: {exc}",
            )
        finally:
            QApplication.restoreOverrideCursor()
            self.install_whisper_cpp.setEnabled(True)

    def _analyze_hardware(self) -> None:
        capabilities = detect_hardware(self.whisper_cpp_executable.text().strip())
        plan = select_inference_plan(
            capabilities,
            performance_mode=str(self.performance_mode.currentData()),
            backend=str(self.backend.currentData()),
            device=str(self.device.currentData()),
            compute_type=str(self.compute_type.currentData()),
            model_name=self._selected_model_value() or "auto",
            whisper_cpp_model=self.whisper_cpp_model.text().strip(),
            whisper_cpp_acceleration=str(self.whisper_cpp_acceleration.currentData()),
        )
        self.hardware_status.setText(hardware_summary(capabilities, plan))
        self.hardware_status.setStyleSheet("color:#48d7aa;")
        self.hardware_status.updateGeometry()

    def apply_to(self, settings: AppSettings) -> None:
        settings.model_name = self._selected_model_value() or "auto"
        settings.language = str(self.language.currentData())
        settings.performance_mode = str(self.performance_mode.currentData())
        settings.inference_backend = str(self.backend.currentData())
        settings.inference_device = str(self.device.currentData())
        settings.compute_type = str(self.compute_type.currentData())
        settings.whisper_cpp_executable = self.whisper_cpp_executable.text().strip()
        settings.whisper_cpp_model = self.whisper_cpp_model.text().strip()
        settings.whisper_cpp_acceleration = str(
            self.whisper_cpp_acceleration.currentData()
        )
        settings.transcription_window_seconds = self.window.value()
        settings.transcription_overlap_seconds = min(
            self.overlap.value(), self.window.value() - 0.5
        )
        settings.low_confidence_second_pass_threshold = self.low_confidence.value()
        settings.recognition_context = self.context.toPlainText().strip()
        settings.vocabulary = [
            item.strip() for item in self.vocabulary.text().split(",") if item.strip()
        ]
        settings.preview_mode = str(self.preview_mode.currentData())
        settings.audio_buffer_seconds = self.audio_buffer.value()
        settings.video_buffer_seconds = self.video_buffer.value()
        settings.merge_nearby_seconds = self.merge_nearby.value()
        settings.auto_save_transcript = self.auto_save.isChecked()
        settings.minimize_to_tray = self.minimize_to_tray.isChecked()
        settings.dynamic_load_adaptation = self.dynamic_load_adaptation.isChecked()
        settings.interface_scale_percent = int(self.interface_scale.currentData() or 100)
        settings.allow_local_control = self.allow_local_control.isChecked()
        settings.reconnect_enabled = self.reconnect_enabled.isChecked()
        settings.reconnect_max_attempts = self.reconnect_attempts.value()
        settings.reconnect_initial_delay_seconds = self.reconnect_initial_delay.value()
        settings.reconnect_max_delay_seconds = max(
            self.reconnect_initial_delay.value(), self.reconnect_max_delay.value()
        )
        root_text = self.diarization_root.text().strip()
        if root_text:
            root = Path(root_text)
            settings.diarization_segmentation_model = str(root / "segmentation.onnx")
            settings.diarization_embedding_model = str(root / "embedding.onnx")
        settings.diarization_cluster_threshold = self.cluster_threshold.value()
        settings.speaker_match_threshold = self.speaker_threshold.value()
        settings.voice_profile_threshold = self.voice_profile_threshold.value()
        settings.diarization_threads = self.diarization_threads.value()


class SpeakerNamesDialog(QDialog):
    def __init__(
        self,
        speakers: list[tuple[str, str]],
        existing: dict[str, str],
        enrollable: set[str] | None = None,
        saved_profiles: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hablantes y perfiles de voz")
        self.setMinimumWidth(650)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Asigna nombres solo cuando reconozcas al hablante. Puedes recordar voluntariamente "
            "una voz para identificarla en sesiones futuras; AuralWarden guarda una huella "
            "numérica local, no la grabación de audio."
        )
        description.setWordWrap(True)
        description.setProperty("muted", True)
        layout.addWidget(description)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        self.inputs: dict[str, QLineEdit] = {}
        self.profile_checks: dict[str, QCheckBox] = {}
        enrollable = enrollable or set()
        for speaker_key, display_name in speakers:
            label = QLabel(display_name)
            label.setToolTip(f"Etiqueta interna de la sesión: {speaker_key}")
            label.setStyleSheet(
                f"color:{speaker_color(display_name)};font-weight:650;"
            )
            editor = QLineEdit(existing.get(speaker_key, ""))
            editor.setPlaceholderText("Nombre visible")
            remember = QCheckBox("Recordar voz")
            remember.setEnabled(speaker_key in enrollable)
            remember.setToolTip(
                "Guardar una huella matemática local de esta voz para reconocerla "
                "en próximas sesiones. Requiere una muestra suficientemente clara."
                if remember.isEnabled()
                else "Esta sesión todavía no tiene suficiente voz limpia para crear el perfil."
            )
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(editor, 1)
            row_layout.addWidget(remember)
            form.addRow(label, row)
            self.inputs[speaker_key] = editor
            self.profile_checks[speaker_key] = remember
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.delete_checks: dict[str, QCheckBox] = {}
        if saved_profiles:
            saved_title = QLabel("Perfiles guardados")
            saved_title.setProperty("title", True)
            layout.addWidget(saved_title)
            saved_note = QLabel(
                "Marca Eliminar únicamente si ya no quieres conservar esa huella de voz."
            )
            saved_note.setProperty("muted", True)
            layout.addWidget(saved_note)
            for profile in saved_profiles:
                remove = QCheckBox(f"Eliminar {profile}")
                remove.setToolTip(
                    "El perfil se borrará al pulsar Aplicar; las transcripciones anteriores no cambian."
                )
                layout.addWidget(remove)
                self.delete_checks[profile] = remove
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aplicar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mapping(self) -> dict[str, str]:
        return {
            speaker: editor.text().strip()
            for speaker, editor in self.inputs.items()
            if editor.text().strip()
        }

    def profile_requests(self) -> dict[str, str]:
        return {
            speaker: self.inputs[speaker].text().strip()
            for speaker, checkbox in self.profile_checks.items()
            if checkbox.isChecked() and self.inputs[speaker].text().strip()
        }

    def profile_deletions(self) -> list[str]:
        return [
            name for name, checkbox in self.delete_checks.items() if checkbox.isChecked()
        ]
