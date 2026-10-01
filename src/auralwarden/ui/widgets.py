from __future__ import annotations

import html
import re
from collections import deque
from pathlib import Path
from typing import Any

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from auralwarden.models import Hotword
from auralwarden.transcript import can_extend_paragraph
from auralwarden.ui.assets import asset_path


_ICON_FONT: qta.IconicFont | None = None


def _portable_icon_font() -> qta.IconicFont:
    """Load only the bundled icon families without installing Windows fonts."""
    global _ICON_FONT
    if _ICON_FONT is None:
        fonts_dir = Path(qta.__file__).resolve().parent / "fonts"
        _ICON_FONT = qta.IconicFont(
            (
                "fa6s",
                "fontawesome6-solid-webfont-6.7.2.ttf",
                "fontawesome6-solid-webfont-charmap-6.7.2.json",
                str(fonts_dir),
            ),
            (
                "fa6b",
                "fontawesome6-brands-webfont-6.7.2.ttf",
                "fontawesome6-brands-webfont-charmap-6.7.2.json",
                str(fonts_dir),
            ),
        )
    return _ICON_FONT


def aw_icon(name: str, color: str = "#91a1aa"):
    try:
        return _portable_icon_font().icon(name, color=color)
    except Exception:
        from PySide6.QtGui import QIcon

        return QIcon()


def card_frame(object_name: str = "") -> QFrame:
    frame = QFrame()
    frame.setProperty("card", True)
    if object_name:
        frame.setObjectName(object_name)
    return frame


class SparklineWidget(QWidget):
    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=42)
        self._color = QColor(color)
        self.setMinimumSize(110, 28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def add_value(self, value: float) -> None:
        self._values.append(max(0.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0a1822"))
        if len(self._values) < 2:
            return
        values = list(self._values)
        maximum = max(max(values), 100.0)
        width = max(1.0, self.width() - 8.0)
        height = max(1.0, self.height() - 8.0)
        path = QPainterPath()
        for index, value in enumerate(values):
            x = 4.0 + width * index / max(1, len(values) - 1)
            y = 4.0 + height * (1.0 - min(value / maximum, 1.0))
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(self._color, 1.7))
        painter.drawPath(path)


class ResourceRow(QWidget):
    def __init__(
        self,
        icon_name: str,
        label: str,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(9)
        icon_label = QLabel()
        icon_label.setPixmap(aw_icon(icon_name, "#b6c5cc").pixmap(22, 22))
        icon_label.setFixedWidth(26)
        self.name_label = QLabel(label)
        self.name_label.setFixedWidth(42)
        self.value_label = QLabel("—")
        self.value_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.value_label.setFixedWidth(84)
        self.graph = SparklineWidget(color)
        self.detail_label = QLabel("")
        self.detail_label.setProperty("muted", True)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.detail_label.setFixedWidth(75)
        layout.addWidget(icon_label)
        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.graph, 1)
        layout.addWidget(self.detail_label)

    def update_value(self, value: float | None, text: str, detail: str = "") -> None:
        self.value_label.setText(text)
        self.detail_label.setText(detail)
        if value is not None:
            self.graph.add_value(value)


class ResourcePanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(0)
        heading = QHBoxLayout()
        title = QLabel("Recursos del sistema")
        title.setProperty("sectionTitle", True)
        self.profile = QLabel("En espera")
        self.profile.setProperty("muted", True)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.profile)
        layout.addLayout(heading)
        self.rows = {
            "audio": ResourceRow("fa6s.wave-square", "Audio", "#a969ff"),
            "gpu": ResourceRow("fa6s.gauge-high", "GPU", "#27c69a"),
            "cpu": ResourceRow("fa6s.microchip", "CPU", "#18baf2"),
            "vram": ResourceRow("fa6s.memory", "VRAM", "#f0ac24"),
            "ram": ResourceRow("fa6s.server", "RAM", "#5ab8ea"),
        }
        for row in self.rows.values():
            layout.addWidget(row)
        footer = QHBoxLayout()
        self.source_label = QLabel("Fuente local")
        self.source_label.setProperty("muted", True)
        self.elapsed_label = QLabel("00:00:00")
        footer.addWidget(self.source_label)
        footer.addStretch()
        footer.addWidget(self.elapsed_label)
        layout.addSpacing(6)
        layout.addLayout(footer)

    def update_snapshot(self, payload: dict[str, Any]) -> None:
        gpu = payload.get("gpu_percent")
        cpu = float(payload.get("cpu_percent") or 0.0)
        memory = float(payload.get("memory_percent") or 0.0)
        vram_used = payload.get("vram_used_mb")
        vram_total = payload.get("vram_total_mb")
        vram_percent = (
            float(vram_used) / float(vram_total) * 100.0
            if vram_used is not None and vram_total
            else None
        )
        self.rows["gpu"].update_value(
            float(gpu) if gpu is not None else None,
            f"{float(gpu):.0f} %" if gpu is not None else "—",
        )
        self.rows["cpu"].update_value(cpu, f"{cpu:.0f} %")
        self.rows["ram"].update_value(
            memory,
            f"{memory:.0f} %",
            f"{float(payload.get('process_memory_mb') or 0):.0f} MB",
        )
        self.rows["vram"].update_value(
            vram_percent,
            f"{float(vram_used) / 1024:.1f} GB" if vram_used is not None else "—",
            f"{float(vram_total) / 1024:.0f} GB" if vram_total else "",
        )
        profile = str(payload.get("profile") or "normal")
        labels = {
            "normal": "Carga normal",
            "constrained": "Carga elevada",
            "critical": "Modo protegido",
        }
        enabled = bool(payload.get("adaptation_enabled", True))
        self.profile.setText(labels.get(profile, profile) if enabled else "Adaptación desactivada")
        source_labels = {"cpu": "CPU", "gpu": "GPU", "ram": "RAM", "vram": "VRAM"}
        pressure_source = source_labels.get(
            str(payload.get("pressure_source") or "cpu"), "recursos"
        )
        pressure = float(payload.get("pressure_percent") or 0.0)
        if enabled:
            self.profile.setToolTip(
                f"La adaptación observa carga sostenida. Mayor presión: {pressure_source} {pressure:.0f} %. "
                "Con carga elevada reduce trabajo secundario; con carga crítica protege el equipo y se recupera gradualmente."
            )
        else:
            self.profile.setToolTip("La adaptación dinámica está desactivada en Preferencias.")

    def update_audio_level(self, level: float) -> None:
        percent = max(0.0, min(100.0, float(level) * 400.0))
        if percent < 0.5:
            text = "Silencio"
        elif percent < 8:
            text = "Bajo"
        elif percent < 35:
            text = "Activo"
        else:
            text = "Alto"
        self.rows["audio"].update_value(percent, text)


class PreviewPanel(QFrame):
    open_requested = Signal()
    toggle_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self._frame_pixmap: QPixmap | None = None
        self._monitoring = False
        self._preview_active = False
        self._demo = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(7)
        self.title_label = QLabel("Transmisión sin identificar")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setProperty("sectionTitle", True)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(42)
        self.title_label.setToolTip("Nombre de la fuente monitorizada")
        layout.addWidget(self.title_label)
        self.image = QLabel()
        self.image.setObjectName("previewImage")
        self.image.setMinimumHeight(180)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background:#08151f; border-radius:7px;")
        layout.addWidget(self.image, 1)
        controls = QHBoxLayout()
        self.live_badge = QLabel("EN ESPERA")
        self.live_badge.setStyleSheet(
            "background:#20333e;color:#bdc9cf;border-radius:4px;padding:4px 7px;font-weight:700;"
        )
        self.time_label = QLabel("00:00:00")
        self.time_label.setProperty("muted", True)
        self.mode_label = QLabel("Vista sincronizada")
        self.mode_label.setProperty("muted", True)
        self.preview_button = QPushButton("Activar vista")
        self.preview_button.setIcon(aw_icon("fa6s.eye", "#c5d0d5"))
        self.preview_button.setProperty("flat", True)
        self.preview_button.setToolTip(
            "Inicia o detiene los fotogramas de previsualización. "
            "El monitoreo de audio continúa aunque la vista esté apagada."
        )
        self.preview_button.clicked.connect(self.toggle_requested)
        self.open_button = QPushButton("Ver directo")
        self.open_button.setIcon(aw_icon("fa6s.arrow-up-right-from-square", "#c5d0d5"))
        self.open_button.setProperty("flat", True)
        self.open_button.clicked.connect(self.open_requested)
        controls.addWidget(self.live_badge)
        controls.addWidget(self.time_label)
        controls.addStretch()
        controls.addWidget(self.mode_label)
        controls.addWidget(self.preview_button)
        controls.addWidget(self.open_button)
        layout.addLayout(controls)
        self.show_idle()

    def set_title(self, title: str, author: str = "") -> None:
        value = " ".join(title.split()) or "Transmisión sin identificar"
        self.title_label.setText(value)
        # Qt tooltips use rich text heuristics; removing markup delimiters keeps
        # remote metadata inert while preserving a compact readable tooltip.
        safe_value = value.replace("<", "‹").replace(">", "›")
        safe_author = " ".join(author.split()).replace("<", "‹").replace(">", "›")
        self.title_label.setToolTip(
            f"{safe_value}\nCanal: {safe_author}" if safe_author else safe_value
        )

    def show_idle(self) -> None:
        self._monitoring = False
        self._preview_active = False
        self._demo = False
        self._show_brand()
        self.preview_button.setText("Activar vista")
        self.preview_button.setIcon(aw_icon("fa6s.eye", "#c5d0d5"))
        self.preview_button.setEnabled(False)
        self.mode_label.setText("Vista apagada")
        self.mode_label.setToolTip("")
        self.live_badge.setText("EN ESPERA")
        self.live_badge.setStyleSheet(
            "background:#20333e;color:#bdc9cf;border-radius:4px;padding:4px 7px;font-weight:700;"
        )

    def _show_brand(self) -> None:
        mark = QPixmap(str(asset_path("brand-mark.png")))
        self._frame_pixmap = None
        self.image.setPixmap(
            mark.scaled(
                260,
                110,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.image.setToolTip(
            "La previsualización está apagada para ahorrar recursos."
        )

    def set_monitoring(self, active: bool, demo: bool = False) -> None:
        self._monitoring = active
        self._demo = demo
        if active:
            self.live_badge.setText("DEMO" if demo else "MONITOREANDO")
            self.live_badge.setStyleSheet(
                "background:#d53b45;color:white;border-radius:4px;padding:4px 7px;font-weight:700;"
            )
            self.preview_button.setEnabled(not demo)
            self.set_preview_active(False)
            if demo:
                self.mode_label.setText("Demostración local")
        else:
            self.show_idle()

    def set_preview_active(self, active: bool) -> None:
        self._preview_active = active and self._monitoring and not self._demo
        if self._preview_active:
            self.preview_button.setText("Desactivar vista")
            self.preview_button.setIcon(aw_icon("fa6s.eye-slash", "#c5d0d5"))
            self.preview_button.setEnabled(True)
            self.mode_label.setText("Preparando vista")
            self.image.setToolTip("Previsualización activa")
            return
        self._show_brand()
        self.preview_button.setText("Activar vista")
        self.preview_button.setIcon(aw_icon("fa6s.eye", "#c5d0d5"))
        self.preview_button.setEnabled(self._monitoring and not self._demo)
        if not self._demo:
            self.mode_label.setText("Vista apagada")

    @property
    def preview_active(self) -> bool:
        return self._preview_active

    def set_frame(self, jpeg: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(jpeg):
            return
        self._frame_pixmap = pixmap
        self._preview_active = True
        self._rescale_frame()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale_frame()

    def _rescale_frame(self) -> None:
        if self._frame_pixmap is None:
            return
        self.image.setPixmap(
            self._frame_pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class CaptionPreviewPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setMinimumHeight(92)
        self.setMaximumHeight(126)
        self._cues: deque[str] = deque(maxlen=3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        title = QLabel("Subtítulos auxiliares de YouTube")
        title.setProperty("sectionTitle", True)
        self.status_label = QLabel("Se mostrarán al iniciar")
        self.status_label.setProperty("muted", True)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.status_label)
        layout.addLayout(heading)
        self.text_label = QLabel(
            "Los últimos subtítulos aparecerán aquí sin mezclarse con Whisper."
        )
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.text_label.setProperty("muted", True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.text_label, 1)
        self.hide()

    def set_option_visible(self, visible: bool) -> None:
        self.setVisible(visible)
        if visible and not self._cues:
            self.status_label.setText("Se mostrarán al iniciar")

    def begin(self) -> None:
        self._cues.clear()
        self.status_label.setText("Buscando pista…")
        self.status_label.setToolTip("")
        self.text_label.setText("Esperando los primeros subtítulos de YouTube…")
        self._set_text_muted(True)

    def set_track(self, language: str = "", automatic: bool | None = None) -> None:
        kind = "automáticos" if automatic else "del canal"
        language_text = language.upper() if language else "Pista activa"
        self.status_label.setText(f"{language_text} · {kind}")
        self.status_label.setToolTip("")

    def set_waiting(self, message: str, delay_seconds: float = 0.0) -> None:
        self.status_label.setText("Esperando pista")
        self.status_label.setToolTip(message)
        if not self._cues:
            delay = max(1, int(round(delay_seconds)))
            self.text_label.setText(
                f"YouTube aún no publica la pista. Nueva consulta en {delay} s…"
            )
            self._set_text_muted(True)

    def set_retrying(self, message: str, delay_seconds: float = 0.0) -> None:
        delay = max(1, int(round(delay_seconds)))
        self.status_label.setText(f"Reintentando · {delay} s")
        self.status_label.setToolTip(message)
        if not self._cues:
            self.text_label.setText(
                "AuralWarden volverá a buscar los subtítulos sin detener Whisper."
            )
            self._set_text_muted(True)

    def set_unavailable(self, message: str, *, retrying: bool = False) -> None:
        self.status_label.setText(
            "No disponibles · reintentando" if retrying else "No disponibles"
        )
        self.status_label.setToolTip(message)
        if not self._cues:
            self.text_label.setText(
                "YouTube no ofrece una pista compatible en este momento."
                + (" AuralWarden seguirá consultándola." if retrying else "")
            )
            self._set_text_muted(True)

    def add_cue(self, text: str, elapsed_seconds: float) -> None:
        clean = " ".join(text.split()).strip()
        if not clean:
            return
        total = max(0, int(elapsed_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        self._cues.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}  {clean}")
        self.text_label.setText("\n".join(self._cues))
        self._set_text_muted(False)
        self.status_label.setText("Recibiendo")

    def finish(self) -> None:
        if self.isVisible():
            self.status_label.setText("Sesión finalizada")

    def _set_text_muted(self, muted: bool) -> None:
        self.text_label.setProperty("muted", muted)
        self.text_label.style().unpolish(self.text_label)
        self.text_label.style().polish(self.text_label)


SPEAKER_COLORS = ("#48d7aa", "#b979ee", "#f0ac24", "#54b9f2", "#ee7d8f")


def speaker_color(speaker: str) -> str:
    return SPEAKER_COLORS[sum(ord(char) for char in speaker) % len(SPEAKER_COLORS)]


class TranscriptRow(QFrame):
    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptParagraph")
        self._parts: list[str] = []
        self._fragment_times: list[tuple[float, float]] = []
        self._fragment_hotwords: list[list[str]] = []
        self._hotwords: list[str] = []
        self._speaker = str(payload.get("speaker_id") or "Speaker")
        self._start_elapsed = self._payload_elapsed(payload)
        self._last_end = self._payload_end(payload)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(2)
        elapsed = max(0, int(self._start_elapsed))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label = QLabel(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.time_label.setProperty("muted", True)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.time_label.setFixedWidth(62)
        self.time_label.setToolTip("Inicio del párrafo")
        self.speaker_label = QLabel(self._speaker)
        self.speaker_label.setStyleSheet(
            f"color:{speaker_color(self._speaker)};font-weight:650;padding-bottom:2px;"
        )
        self.text_label = QLabel()
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.text_label.setOpenExternalLinks(False)
        self.text_label.linkHovered.connect(self._show_fragment_time)
        self.text_label.linkActivated.connect(self._show_fragment_time)
        self.refined = QLabel("segunda pasada")
        self.refined.setProperty("muted", True)
        self.refined.setStyleSheet("font-size:11px;")
        self.refined.setToolTip(
            "El audio fue analizado una segunda vez; no significa que el texto sea infalible."
        )
        self.refined.hide()
        layout.addWidget(self.time_label, 0, 0, 2, 1)
        layout.addWidget(self.speaker_label, 0, 1)
        layout.addWidget(self.text_label, 1, 1)
        layout.addWidget(self.refined, 0, 2, alignment=Qt.AlignmentFlag.AlignRight)
        layout.setColumnStretch(1, 1)
        self.append_payload(payload)

    @staticmethod
    def _payload_elapsed(payload: dict[str, Any]) -> float:
        return max(0.0, float(payload.get("elapsed_seconds") or 0.0))

    @classmethod
    def _payload_end(cls, payload: dict[str, Any]) -> float:
        start = cls._payload_elapsed(payload)
        return max(start, float(payload.get("end_seconds") or start))

    @property
    def plain_text(self) -> str:
        return " ".join(self._parts)

    def can_append(self, payload: dict[str, Any]) -> bool:
        return can_extend_paragraph(
            self._speaker,
            self._start_elapsed,
            self._last_end,
            len(self.plain_text),
            str(payload.get("speaker_id") or "Speaker"),
            self._payload_elapsed(payload),
        )

    def append_payload(self, payload: dict[str, Any]) -> None:
        text = " ".join(str(payload.get("text") or "").split())
        fragment_hotwords = [str(item) for item in payload.get("hotwords") or []]
        fragment_start = self._payload_elapsed(payload)
        if text:
            self._parts.append(text)
            self._fragment_times.append(
                (fragment_start, self._payload_end(payload))
            )
            self._fragment_hotwords.append(fragment_hotwords)
        self._start_elapsed = min(self._start_elapsed, fragment_start)
        self.time_label.setText(self._format_timestamp(self._start_elapsed))
        self._last_end = max(self._last_end, self._payload_end(payload))
        for phrase in fragment_hotwords:
            if phrase and phrase.casefold() not in {
                existing.casefold() for existing in self._hotwords
            }:
                self._hotwords.append(phrase)
        if payload.get("second_pass"):
            self.refined.show()
        self._render()

    def _render(self) -> None:
        fragments: list[str] = []
        for index, (part, hotwords) in enumerate(
            zip(self._parts, self._fragment_hotwords, strict=True)
        ):
            text = html.escape(part)
            for phrase in sorted(hotwords, key=len, reverse=True):
                pattern = re.compile(re.escape(html.escape(phrase)), re.IGNORECASE)
                text = pattern.sub(
                    lambda match: (
                        '<span style="background:#8c6412;color:#ffe3a0;'
                        f'padding:1px 3px;">{match.group(0)}</span>'
                    ),
                    text,
                )
            tooltip = html.escape(self.fragment_time_text(f"awtime:{index}"), quote=True)
            fragments.append(
                f'<a href="awtime:{index}" title="{tooltip}" '
                f'style="color:#e7eef2;text-decoration:none;">{text}</a>'
            )
        self.text_label.setText(" ".join(fragments))
        if self._hotwords:
            self.setStyleSheet(
                "QFrame#transcriptParagraph {background:#11382f;"
                "border:1px solid #1c5a49;border-radius:7px;}"
            )
            self.text_label.setStyleSheet("font-size:15px;font-weight:600;")
        else:
            self.setStyleSheet(
                "QFrame#transcriptParagraph {background:transparent;"
                "border:none;border-radius:7px;} "
                "QFrame#transcriptParagraph:hover{background:#0f232e;}"
            )
            self.text_label.setStyleSheet("")

    def fragment_time_text(self, link: str) -> str:
        if not link.startswith("awtime:"):
            return ""
        try:
            index = int(link.removeprefix("awtime:"))
            start, end = self._fragment_times[index]
        except (ValueError, IndexError):
            return ""
        start_text = self._format_timestamp(start)
        end_text = self._format_timestamp(end)
        if end_text == start_text:
            return f"Fragmento: {start_text}"
        return f"Fragmento: {start_text}–{end_text}"

    def _show_fragment_time(self, link: str) -> None:
        message = self.fragment_time_text(link)
        if not message:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(), message, self.text_label)

    @staticmethod
    def _format_timestamp(value: float) -> str:
        total = max(0, int(value))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class TranscriptFeed(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        heading = QHBoxLayout()
        title = QLabel("Transcripción en tiempo real")
        title.setProperty("title", True)
        self.count_label = QLabel("Sin actividad")
        self.count_label.setProperty("muted", True)
        language = QLabel("ES")
        language.setStyleSheet("border:1px solid #29414f;border-radius:5px;padding:5px 9px;")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.count_label)
        heading.addWidget(language)
        layout.addLayout(heading)
        self.caption_preview = CaptionPreviewPanel(self)
        layout.addWidget(self.caption_preview)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 6, 0, 6)
        self.rows.setSpacing(3)
        self.empty = QLabel("La transcripción aparecerá aquí al iniciar el monitoreo.")
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows.addWidget(self.empty, 1)
        self.rows.addStretch()
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self._count = 0
        self._paragraph_count = 0
        self._last_row: TranscriptRow | None = None

    def clear(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.empty = QLabel("La transcripción aparecerá aquí al iniciar el monitoreo.")
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows.addWidget(self.empty, 1)
        self.rows.addStretch()
        self._count = 0
        self._paragraph_count = 0
        self._last_row = None
        self.count_label.setText("Sin actividad")

    def append_entry(self, payload: dict[str, Any]) -> None:
        if self._count == 0:
            self.rows.removeWidget(self.empty)
            self.empty.setParent(None)
            self.empty.deleteLater()
        if self._last_row is not None and self._last_row.can_append(payload):
            self._last_row.append_payload(payload)
        else:
            self._last_row = TranscriptRow(payload)
            self.rows.insertWidget(
                max(0, self.rows.count() - 1), self._last_row
            )
            self._paragraph_count += 1
        self._count += 1
        unit = "fragmento" if self._count == 1 else "fragmentos"
        paragraph_unit = "párrafo" if self._paragraph_count == 1 else "párrafos"
        self.count_label.setText(
            f"{self._count} {unit} · {self._paragraph_count} {paragraph_unit}"
        )
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class ActivityCard(QFrame):
    open_requested = Signal(str)

    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.event_id = str(payload.get("event_id") or "")
        self._expected_media = {
            media_type
            for media_type, requested in (
                ("audio/wav", payload.get("audio_clip_requested")),
                ("video/mp4", payload.get("video_clip_requested")),
            )
            if bool(requested)
        }
        self._ready_media: dict[str, tuple[str, bool]] = {}
        self.setStyleSheet(
            "QFrame{background:#102a2c;border:1px solid #1f4b48;border-radius:7px;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(4)
        top = QHBoxLayout()
        elapsed = max(0, int(float(payload.get("elapsed_seconds") or 0)))
        minutes, seconds = divmod(elapsed, 60)
        timestamp = QLabel(f"{minutes:02d}:{seconds:02d}")
        timestamp.setProperty("muted", True)
        now = QLabel("Ahora")
        now.setProperty("muted", True)
        top.addWidget(timestamp)
        top.addStretch()
        top.addWidget(now)
        layout.addLayout(top)
        phrase = QLabel(str(payload.get("phrase") or "Coincidencia"))
        phrase.setStyleSheet("color:#48d7aa;font-size:15px;font-weight:650;")
        layout.addWidget(phrase)
        speaker = str(payload.get("speaker_id") or "").strip()
        if speaker:
            speaker_label = QLabel(f"Dicho por {speaker}")
            speaker_label.setStyleSheet(
                f"color:{speaker_color(speaker)};font-weight:600;"
            )
            layout.addWidget(speaker_label)
        self.score_text = QLabel(f"Coincidencia {float(payload.get('score') or 0):.0f} %")
        self.score_text.setStyleSheet("color:#5ee0b9;")
        score_row = QHBoxLayout()
        score_icon = QLabel()
        score_icon.setPixmap(aw_icon("fa6s.crosshairs", "#48d7aa").pixmap(14, 14))
        score_row.addWidget(score_icon)
        score_row.addWidget(self.score_text)
        score_row.addStretch()
        layout.addLayout(score_row)
        if self._expected_media == {"audio/wav", "video/mp4"}:
            pending_text = "Preparando clips de audio y vídeo…"
        elif "video/mp4" in self._expected_media:
            pending_text = "Preparando clip de vídeo…"
        elif "audio/wav" in self._expected_media:
            pending_text = "Preparando clip de audio…"
        else:
            pending_text = "Alerta registrada"
        self.clip_label = QLabel(pending_text)
        self.clip_label.setProperty("muted", True)
        layout.addWidget(self.clip_label)
        self.evidence_row = QHBoxLayout()
        self.evidence_row.setSpacing(5)
        self.evidence_row.addStretch()
        layout.addLayout(self.evidence_row)
        self._media_buttons: dict[str, QPushButton] = {}

    def set_clip_ready(self, path: str, truncated: bool, media_type: str) -> None:
        self._ready_media[media_type] = (path, truncated)
        has_audio = "audio/wav" in self._ready_media
        has_video = "video/mp4" in self._ready_media
        if has_audio and has_video:
            label = "Clips de audio y vídeo creados"
        elif has_video:
            label = "Clip de vídeo creado"
        else:
            label = "Clip de audio creado"
        if any(item[1] for item in self._ready_media.values()):
            label += " · parcial"
        self.clip_label.setText(label)
        self.clip_label.setToolTip(
            "\n".join(item[0] for item in self._ready_media.values())
        )
        if media_type not in self._media_buttons:
            text = "Abrir vídeo" if media_type == "video/mp4" else "Abrir audio"
            icon = "fa6s.video" if media_type == "video/mp4" else "fa6s.wave-square"
            button = QPushButton(text)
            button.setIcon(aw_icon(icon, "#b8c8ce"))
            button.setProperty("flat", True)
            button.setToolTip(path)
            button.clicked.connect(
                lambda _checked=False, target=path: self.open_requested.emit(target)
            )
            self.evidence_row.insertWidget(
                max(0, self.evidence_row.count() - 1), button
            )
            self._media_buttons[media_type] = button

    def set_clip_failed(self, message: str) -> None:
        self.clip_label.setText("No se pudo crear el clip de vídeo")
        self.clip_label.setToolTip(message)


class ActivityFeed(QFrame):
    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        heading = QHBoxLayout()
        title = QLabel("Actividad reciente")
        title.setProperty("title", True)
        self.total = QLabel("0 alertas")
        self.total.setProperty("muted", True)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.total)
        layout.addLayout(heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.cards = QVBoxLayout(self.content)
        self.cards.setContentsMargins(0, 5, 0, 5)
        self.cards.setSpacing(8)
        self.empty = QLabel("Las coincidencias aparecerán aquí.")
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.cards.addWidget(self.empty, 1)
        self.cards.addStretch()
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self._by_event: dict[str, ActivityCard] = {}

    def clear(self) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._by_event.clear()
        self.empty = QLabel("Las coincidencias aparecerán aquí.")
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.cards.addWidget(self.empty, 1)
        self.cards.addStretch()
        self.total.setText("0 alertas")

    def add_detection(self, payload: dict[str, Any]) -> None:
        event_id = str(payload.get("event_id") or "")
        if event_id in self._by_event:
            return
        if not self._by_event:
            self.cards.removeWidget(self.empty)
            self.empty.setParent(None)
            self.empty.deleteLater()
        card = ActivityCard(payload)
        card.open_requested.connect(lambda path: self.open_requested.emit(path))
        self.cards.insertWidget(0, card)
        self._by_event[event_id] = card
        count = len(self._by_event)
        unit = "alerta" if count == 1 else "alertas"
        self.total.setText(f"{count} {unit}")

    def mark_clip(self, payload: dict[str, Any]) -> None:
        card = self._by_event.get(str(payload.get("event_id") or ""))
        if card is not None:
            card.set_clip_ready(
                str(payload.get("path") or ""),
                bool(payload.get("truncated")),
                str(payload.get("media_type") or "audio/wav"),
            )

    def mark_clip_failed(self, payload: dict[str, Any]) -> None:
        card = self._by_event.get(str(payload.get("event_id") or ""))
        if card is not None:
            card.set_clip_failed(str(payload.get("message") or "Error desconocido"))


class HotwordEditor(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._speaker_profiles: list[str] = []
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        heading = QHBoxLayout()
        title = QLabel("Hotwords")
        title.setProperty("title", True)
        add = QPushButton("Agregar")
        add.setIcon(aw_icon("fa6s.plus", "#b8c8ce"))
        add.setProperty("flat", True)
        add.setToolTip("Añadir otra palabra o frase que AuralWarden debe detectar")
        add.clicked.connect(lambda: self.add_hotword(Hotword("", threshold=88)))
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(add)
        layout.addLayout(heading)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Palabra o frase", "Umbral", "Hablante", ""]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 42)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table, 1)
        note = QLabel(
            "La coincidencia se evalúa localmente; un umbral menor recupera más menciones. "
            "Elegir un perfil de voz activa la separación de hablantes."
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)
        layout.addWidget(note)

    def set_hotwords(self, hotwords: list[Hotword]) -> None:
        self.table.setRowCount(0)
        for hotword in hotwords:
            self.add_hotword(hotword)

    def set_speaker_profiles(self, names: list[str]) -> None:
        self._speaker_profiles = sorted(
            {str(name).strip() for name in names if str(name).strip()},
            key=str.casefold,
        )
        for row in range(self.table.rowCount()):
            selector = self.table.cellWidget(row, 2)
            if not isinstance(selector, QComboBox):
                continue
            selected = str(selector.currentData() or "")
            self._populate_speaker_selector(selector, selected)

    def add_hotword(self, hotword: Hotword) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        phrase = QLineEdit(hotword.phrase)
        phrase.setPlaceholderText("Nueva palabra")
        phrase.setMinimumHeight(38)
        phrase.setToolTip(
            "Palabra o frase que debe activar la alerta. "
            "Puede contener varias palabras."
        )
        phrase.textChanged.connect(self.changed)
        threshold = QSpinBox()
        threshold.setRange(50, 100)
        threshold.setSuffix(" %")
        threshold.setValue(hotword.threshold)
        threshold.setMinimumHeight(38)
        threshold.setToolTip(
            "Similitud mínima para aceptar la coincidencia. "
            "Un valor menor recupera más menciones, pero puede aumentar falsos positivos."
        )
        threshold.valueChanged.connect(self.changed)
        speaker = QComboBox()
        speaker.setMinimumHeight(38)
        speaker.setMinimumWidth(190)
        speaker.setToolTip(
            "Limita esta hotword a una voz recordada. Si eliges cualquier hablante, "
            "la alerta funcionará aunque la diarización no reconozca una identidad."
        )
        self._populate_speaker_selector(speaker, hotword.speaker_profile)
        speaker.currentIndexChanged.connect(self.changed)
        remove = QPushButton()
        remove.setIcon(aw_icon("fa6s.trash", "#d58d94"))
        remove.setProperty("flat", True)
        remove.setToolTip("Eliminar hotword")
        remove.clicked.connect(lambda checked=False, widget=remove: self._remove_widget_row(widget))
        self.table.setCellWidget(row, 0, phrase)
        self.table.setCellWidget(row, 1, threshold)
        self.table.setCellWidget(row, 2, speaker)
        self.table.setCellWidget(row, 3, remove)
        self.table.setRowHeight(row, 48)
        if not hotword.phrase:
            phrase.setFocus()

    def _remove_widget_row(self, widget: QWidget) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 3) is widget:
                self.table.removeRow(row)
                self.changed.emit()
                return

    def _populate_speaker_selector(self, selector: QComboBox, selected: str) -> None:
        selector.blockSignals(True)
        selector.clear()
        selector.addItem("Cualquier hablante", "")
        for name in self._speaker_profiles:
            selector.addItem(name, name)
        if selected and selected not in self._speaker_profiles:
            selector.addItem(f"{selected} (no disponible)", selected)
        index = selector.findData(selected)
        selector.setCurrentIndex(max(0, index))
        selector.blockSignals(False)

    def hotwords(self) -> list[Hotword]:
        result: list[Hotword] = []
        seen: set[str] = set()
        for row in range(self.table.rowCount()):
            phrase_widget = self.table.cellWidget(row, 0)
            threshold_widget = self.table.cellWidget(row, 1)
            speaker_widget = self.table.cellWidget(row, 2)
            if not isinstance(phrase_widget, QLineEdit) or not isinstance(
                threshold_widget, QSpinBox
            ):
                continue
            phrase = phrase_widget.text().strip()
            key = phrase.casefold()
            if phrase and key not in seen:
                speaker_profile = (
                    str(speaker_widget.currentData() or "")
                    if isinstance(speaker_widget, QComboBox)
                    else ""
                )
                result.append(
                    Hotword(
                        phrase,
                        threshold=threshold_widget.value(),
                        speaker_profile=speaker_profile,
                    )
                )
                seen.add(key)
        return result


class QuickSettingsPanel(QFrame):
    preferences_requested = Signal()
    test_sound_requested = Signal()
    test_notification_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        heading = QHBoxLayout()
        title = QLabel("Clips y notificaciones")
        title.setProperty("title", True)
        preferences = QPushButton("Preferencias")
        preferences.setIcon(aw_icon("fa6s.sliders", "#b8c8ce"))
        preferences.setProperty("flat", True)
        preferences.setToolTip(
            "Abrir configuración avanzada de reconocimiento, rendimiento y hablantes"
        )
        preferences.clicked.connect(self.preferences_requested)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(preferences)
        layout.addLayout(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Clip automático"), 0, 0, 1, 2)
        self.pre_seconds = QSpinBox()
        self.pre_seconds.setRange(0, 60)
        self.pre_seconds.setSuffix(" s antes")
        self.pre_seconds.setToolTip(
            "Cantidad de audio o vídeo anterior a la hotword que se incluirá en el clip"
        )
        self.post_seconds = QSpinBox()
        self.post_seconds.setRange(0, 120)
        self.post_seconds.setSuffix(" s después")
        self.post_seconds.setToolTip(
            "Cantidad de audio o vídeo posterior a la hotword que se incluirá en el clip"
        )
        grid.addWidget(self.pre_seconds, 1, 0)
        grid.addWidget(self.post_seconds, 1, 1)
        self.save_full_audio = QCheckBox("Guardar audio completo")
        self.save_full_audio.setToolTip(
            "Conservar todo el audio de la sesión; aumenta el uso de disco"
        )
        self.save_event_clips = QCheckBox("Clip de audio")
        self.save_event_clips.setToolTip("Crear un WAV cuando se detecte una hotword")
        self.save_event_video_clips = QCheckBox("Clip de vídeo")
        self.save_event_video_clips.setToolTip(
            "Crear un MP4 con vídeo y audio cuando se detecte una hotword"
        )
        self.save_full_video = QCheckBox("Guardar vídeo completo")
        self.save_full_video.setToolTip(
            "Conservar todo el vídeo de la sesión. Puede ocupar varios gigabytes en directos largos"
        )
        self.use_youtube_captions = QCheckBox("Ayuda de subtítulos")
        self.use_youtube_captions.setToolTip(
            "En YouTube, usa los subtítulos disponibles como segunda fuente para detectar hotwords; Whisper sigue siendo la fuente principal"
        )
        self.diarization = QCheckBox("Separar hablantes")
        self.diarization.setToolTip(
            "Intentar distinguir las intervenciones de diferentes personas usando modelos locales"
        )
        self.expected_speakers = QSpinBox()
        self.expected_speakers.setRange(0, 20)
        self.expected_speakers.setSpecialValueText("Automático")
        self.expected_speakers.setToolTip(
            "Límite de identidades durante toda la sesión. Automático estima la cantidad; si conoce el número real, indicarlo evita etiquetas adicionales"
        )
        grid.addWidget(self.save_event_clips, 2, 0)
        grid.addWidget(self.save_event_video_clips, 2, 1)
        grid.addWidget(self.save_full_audio, 3, 0)
        grid.addWidget(self.save_full_video, 3, 1)
        grid.addWidget(self.use_youtube_captions, 4, 0, 1, 2)
        grid.addWidget(self.diarization, 5, 0)
        grid.addWidget(self.expected_speakers, 5, 1)
        grid.addWidget(QLabel("Notificación"), 6, 0)
        self.notification_mode = QComboBox()
        self.notification_mode.addItems(["Sonido + Windows", "Solo Windows", "Solo sonido", "Silenciosa"])
        self.notification_mode.setToolTip(
            "Elige cómo avisará AuralWarden cuando detecte una hotword"
        )
        grid.addWidget(self.notification_mode, 6, 1)
        self.sound = QComboBox()
        self.sound.addItems(["Alerta amable", "Aviso", "Discreta"])
        self.sound.setToolTip("Selecciona el sonido local de las alertas")
        grid.addWidget(QLabel("Sonido"), 7, 0)
        grid.addWidget(self.sound, 7, 1)
        test_row = QHBoxLayout()
        self.test_sound = QPushButton("Probar sonido")
        self.test_sound.setIcon(aw_icon("fa6s.volume-high", "#b8c8ce"))
        self.test_sound.setToolTip(
            "Reproduce inmediatamente el sonido seleccionado, sin guardar cambios"
        )
        self.test_sound.clicked.connect(self.test_sound_requested)
        self.test_notification = QPushButton("Probar aviso")
        self.test_notification.setIcon(aw_icon("fa6s.bell", "#b8c8ce"))
        self.test_notification.setToolTip(
            "Emite una alerta de prueba usando el modo y sonido seleccionados"
        )
        self.test_notification.clicked.connect(self.test_notification_requested)
        test_row.addWidget(self.test_sound)
        test_row.addWidget(self.test_notification)
        grid.addLayout(test_row, 8, 0, 1, 2)
        layout.addLayout(grid)
        layout.addStretch()
