from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                              QPushButton, QVBoxLayout)

from auralwarden import __version__
from auralwarden.paths import application_root
from auralwarden.ui.assets import asset_path
from auralwarden.ui.typography import ParagraphTextEdit


class AboutDialog(QDialog):
    def __init__(self, parent=None, *, root: Path | None = None):
        super().__init__(parent)
        self.root = root or application_root()
        self.setWindowTitle("Acerca de AuralWarden")
        self.resize(620, 420)
        self.setMinimumSize(440, 360)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(asset_path("app-icon.png"))).scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(logo)
        title = QLabel(f"AuralWarden {__version__}\nCreado por Yojemr")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(title, 1)
        layout.addLayout(header)
        self.body = ParagraphTextEdit()
        self.body.setReadOnly(True)
        self.body.setFrameShape(ParagraphTextEdit.Shape.NoFrame)
        self.body.setHtml(
            '<p>Software libre bajo GNU GPL versión 3 exclusivamente. Puedes copiarlo y '
            'modificarlo bajo esos términos. Se proporciona SIN GARANTÍA.</p>'
            '<p>Los componentes, modelos, iconos y herramientas de terceros conservan sus '
            'propias licencias. Los siguientes documentos están incluidos en la carpeta '
            'de AuralWarden:</p>'
            '<p>LICENSE<br>NOTICE<br>docs/THIRD_PARTY_NOTICES.md</p>'
            f'<p>Carpeta de la aplicación:<br>{escape(str(self.root))}</p>'
        )
        layout.addWidget(self.body, 1)
        notices = QPushButton("Abrir avisos de terceros")
        self.notices_path = self.root / "docs" / "THIRD_PARTY_NOTICES.md"
        notices.setEnabled(self.notices_path.is_file())
        notices.setToolTip(str(self.notices_path))
        notices.clicked.connect(self.open_notices)
        layout.addWidget(notices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def open_notices(self):
        if self.notices_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.notices_path)))
