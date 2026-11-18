import pytest

_QT_TEST_APPLICATION = None


@pytest.fixture(scope="session", autouse=True)
def qt_application_lifetime():
    global _QT_TEST_APPLICATION
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    _QT_TEST_APPLICATION = QApplication.instance() or QApplication([])
    yield _QT_TEST_APPLICATION


@pytest.fixture(autouse=True)
def offline_ui_source_metadata(monkeypatch):
    from auralwarden.source_info import fallback_source_info
    from auralwarden.ui import source_info
    monkeypatch.setattr(source_info, "resolve_source_info", fallback_source_info)


@pytest.fixture(autouse=True)
def isolated_application_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AURALWARDEN_DATA_DIR", str(tmp_path / "synthetic-app-data"))


@pytest.fixture(autouse=True)
def dispose_test_windows(qt_application_lifetime):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from shiboken6 import isValid
    from auralwarden.engine import MonitoringEngine
    from auralwarden.ui.controller import MonitoringController
    from auralwarden.ui.media_review import MediaReviewPanel

    app = qt_application_lifetime
    previous = {id(widget) for widget in app.topLevelWidgets()}
    yield
    owned = [widget for widget in app.topLevelWidgets() if id(widget) not in previous]
    for widget in owned:
        if not isValid(widget):
            continue
        for timer in widget.findChildren(QTimer):
            timer.stop()
        controller = getattr(widget, "controller", None)
        if (isinstance(controller, MonitoringController)
                and (controller.engine is None or isinstance(controller.engine, MonitoringEngine))):
            assert controller.stop_and_wait(5), "A synthetic monitoring worker did not stop"
            controller.close()
        preview = getattr(widget, "preview", None)
        if preview is not None and callable(getattr(preview, "stop", None)):
            preview.stop()
        panels = ([widget] if isinstance(widget, MediaReviewPanel) else []) + widget.findChildren(MediaReviewPanel)
        for panel in panels:
            if panel.busy:
                panel.worker.cancel.set()
                assert panel.worker.wait(10_000), "A synthetic export worker did not stop"
            panel.reset()
        tray = getattr(widget, "tray", None)
        if tray is not None:
            tray.hide()
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
