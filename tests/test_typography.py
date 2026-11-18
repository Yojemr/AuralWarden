import pytest

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from auralwarden.ui.about_dialog import AboutDialog
from auralwarden.ui.typography import (ParagraphTextEdit, install_message_typography,
                                      remove_message_typography, justify_label)


@pytest.fixture
def app(qt_application_lifetime):
    application = qt_application_lifetime
    yield application
    remove_message_typography(application)
    application.processEvents()


def test_body_alignment_does_not_change_text_or_links(app):
    text = '<p>Un párrafo con <a href="awtime:0">una frase</a> y contenido.</p>'
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(False)
    justify_label(label)
    assert label.text() == text
    assert label.wordWrap()
    assert label.alignment() & Qt.AlignmentFlag.AlignJustify
    assert not label.openExternalLinks()


@pytest.mark.parametrize("text", ["Primer párrafo.\nSegundo párrafo.", "<img src=file:///private> & texto", ""])
def test_editor_replacement_preserves_literal_text_and_justifies_all_blocks(app, text):
    editor = ParagraphTextEdit()
    editor.setPlainText("Texto anterior")
    editor.setPlainText(text)
    assert editor.toPlainText() == text
    assert not editor.document().isModified()
    block = editor.document().begin()
    while block.isValid():
        assert block.blockFormat().alignment() & Qt.AlignmentFlag.AlignJustify
        block = block.next()
    assert editor.document().defaultTextOption().wrapMode() == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere


def test_about_uses_resizable_scrollable_text_and_complete_notice_path(app, tmp_path, monkeypatch):
    from auralwarden.ui import about_dialog as ui
    notice = tmp_path / "docs" / "THIRD_PARTY_NOTICES.md"
    notice.parent.mkdir()
    notice.write_text("Synthetic local document", encoding="utf-8")
    dialog = AboutDialog(root=tmp_path)
    dialog.resize(440, 360)
    dialog.show()
    app.processEvents()
    assert "docs/THIRD_PARTY_NOTICES.md" in dialog.body.toPlainText()
    assert str(tmp_path) in dialog.body.toPlainText()
    assert dialog.body.isReadOnly()
    assert dialog.body.horizontalScrollBar().maximum() == 0
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    dialog.open_notices()
    assert opened == [QUrl.fromLocalFile(str(notice))]
    notice.unlink()
    dialog.open_notices()
    assert len(opened) == 1
    dialog.close()


def test_long_unbroken_path_wraps_without_losing_characters(app, tmp_path):
    editor = ParagraphTextEdit()
    text = str(tmp_path / ("very_long_directory_" * 20) / "THIRD_PARTY_NOTICES.md")
    editor.setPlainText(text)
    editor.resize(320, 220)
    editor.show()
    app.processEvents()
    assert editor.toPlainText() == text
    assert editor.horizontalScrollBar().maximum() == 0
    assert editor.document().begin().layout().lineCount() > 1
    editor.close()


def test_transcript_justification_keeps_hotword_and_fragment_times(app):
    from auralwarden.ui.widgets import TranscriptRow
    row = TranscriptRow({"text": "Esta es la palabra clave que se dijo.", "speaker_id": "Speaker 1",
                         "elapsed_seconds": 10, "end_seconds": 12, "hotwords": ["palabra clave"]})
    row.append_payload({"text": "Y este fragmento viene después.", "speaker_id": "Speaker 1",
                        "elapsed_seconds": 12, "end_seconds": 14})
    assert row.text_label.alignment() & Qt.AlignmentFlag.AlignJustify
    assert 'align="justify"' in row.text_label.text()
    assert "awtime:0" in row.text_label.text() and "awtime:1" in row.text_label.text()
    assert "background:#8c6412" in row.text_label.text()
    assert row.fragment_time_text("awtime:1") == "Fragmento: 00:00:12–00:00:14"
    assert row.plain_text == "Esta es la palabra clave que se dijo. Y este fragmento viene después."


def test_standard_messages_keep_buttons_and_justify_body(app):
    install_message_typography(app)
    handler = app._auralwarden_message_typography
    install_message_typography(app)
    assert app._auralwarden_message_typography is handler
    box = QMessageBox(QMessageBox.Icon.Warning, "Título", "Un mensaje suficientemente largo para varias líneas.",
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setInformativeText("Detalle adicional de la operación.")
    box.show()
    app.processEvents()
    for label in box.findChildren(QLabel):
        if label.objectName() in {"qt_msgbox_label", "qt_msgbox_informativelabel"}:
            assert label.alignment() & Qt.AlignmentFlag.AlignJustify
    assert box.defaultButton() is box.button(QMessageBox.StandardButton.No)
    box.close()
    remove_message_typography(app)
    assert not hasattr(app, "_auralwarden_message_typography")


def test_editable_context_keeps_new_paragraphs_justified(app):
    editor = ParagraphTextEdit("Contexto inicial")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("\nMás contexto")
    assert editor.toPlainText() == "Contexto inicial\nMás contexto"
    assert editor.document().lastBlock().blockFormat().alignment() & Qt.AlignmentFlag.AlignJustify


def test_preferences_scroll_instead_of_overlapping_hardware_panel(app):
    from PySide6.QtWidgets import QScrollArea, QTabWidget
    from auralwarden.models import AppSettings
    from auralwarden.ui.dialogs import PreferencesDialog
    dialog = PreferencesDialog(AppSettings())
    dialog.show()
    app.processEvents()
    tabs = dialog.findChild(QTabWidget)
    assert all(isinstance(tabs.widget(index), QScrollArea) for index in range(tabs.count()))
    area = tabs.widget(0)
    area.setFixedHeight(260)
    app.processEvents()
    assert area.verticalScrollBar().maximum() > 0
    assert dialog.hardware_status.alignment() & Qt.AlignmentFlag.AlignJustify
    panel = dialog.hardware_panel
    assert dialog.analyze_hardware.geometry().bottom() <= panel.height()
    dialog.close()


def test_bookmark_notes_are_wrapped_and_justified(app, tmp_path):
    from auralwarden.bookmarks import BookmarkStore
    from auralwarden.ui.moments_dialog import MomentsDialog
    store = BookmarkStore(tmp_path / "bookmarks.json")
    text = "Una nota de ejemplo para comprobar que el texto se mantiene completo. " * 5
    store.add(tmp_path / "session", 15, text)
    dialog = MomentsDialog(store, tmp_path / "session")
    dialog.show()
    app.processEvents()
    assert dialog.items.item(0).textAlignment() & Qt.AlignmentFlag.AlignJustify
    assert text.strip() in dialog.items.item(0).text()
    assert dialog.items.wordWrap()
    assert dialog.items.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    dialog.close()
