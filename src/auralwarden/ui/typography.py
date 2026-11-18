from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QTextBlockFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextEdit


def justify_label(label: QLabel) -> None:
    """Align body copy without changing its text, links or interaction flags."""
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignJustify | Qt.AlignmentFlag.AlignTop)


def justify_document(editor: QTextEdit) -> None:
    document = editor.document()
    option = document.defaultTextOption()
    option.setAlignment(Qt.AlignmentFlag.AlignJustify)
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    modified = document.isModified()
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    block_format = QTextBlockFormat()
    block_format.setAlignment(Qt.AlignmentFlag.AlignJustify)
    cursor.mergeBlockFormat(block_format)
    document.setModified(modified)


class ParagraphTextEdit(QTextEdit):
    """Keep paragraph alignment when loading or replacing text."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        justify_document(self)

    def setPlainText(self, text: str) -> None:
        super().setPlainText(text)
        justify_document(self)

    def setHtml(self, text: str) -> None:
        super().setHtml(text)
        justify_document(self)


class MessageTypography(QObject):
    """Apply the same body alignment to Qt's native message-box labels."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QMessageBox):
            for label in watched.findChildren(QLabel):
                if label.objectName() in {"qt_msgbox_label", "qt_msgbox_informativelabel"}:
                    justify_label(label)
        return False


def install_message_typography(app: QApplication) -> None:
    if not hasattr(app, "_auralwarden_message_typography"):
        handler = MessageTypography(app)
        app.installEventFilter(handler)
        app._auralwarden_message_typography = handler


def remove_message_typography(app: QApplication) -> None:
    handler = getattr(app, "_auralwarden_message_typography", None)
    if handler is not None:
        app.removeEventFilter(handler)
        del app._auralwarden_message_typography
        handler.deleteLater()
