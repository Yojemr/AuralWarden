import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from auralwarden.models import AppSettings
from auralwarden.ui.setup_dialog import ModelSetupDialog, SetupWorker


def test_dialog_cancel_does_not_destroy_active_worker(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = ModelSetupDialog(AppSettings(), root=tmp_path, analyze=False)
    import threading
    fake = SimpleNamespace(cancel=threading.Event())
    dialog.worker = fake
    dialog.show()
    dialog.close()
    app.processEvents()
    assert fake.cancel.is_set() and dialog.isVisible()
    dialog.worker = None
    dialog.close()


def test_dialog_recommendation_and_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = ModelSetupDialog(AppSettings(), root=tmp_path, analyze=False)
    dialog._result({"recommended": "base", "summary": "CPU / int8"})
    assert dialog.model.currentData() == "base"
    dialog._result({"model": str(tmp_path / "models" / "base"), "speakers": None})
    dialog._finished()
    assert dialog.progress.value() == 100
    assert dialog.prepare.text() == "Usar este modelo"
    dialog._prepare()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()
    app.processEvents()


def test_dialog_highlights_cuda_when_nvidia_is_compatible(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = ModelSetupDialog(AppSettings(), root=tmp_path, analyze=False)
    dialog._result({
        "recommended": "base",
        "summary": "CPU disponible; CUDA ideal.",
        "cuda_recommended": True,
        "ideal_model": "large-v3-turbo",
    })

    assert "recomendado" in dialog.cuda_button.text().casefold()
    assert "large-v3-turbo" in dialog.status.text()
    assert dialog.model.currentData() == "base"
    dialog.close()
    app.processEvents()


def test_worker_errors_never_expose_urls_or_credentials(tmp_path, monkeypatch):
    from auralwarden.ui import setup_dialog as module
    monkeypatch.setattr(module, "resolve_local_whisper_model", lambda _: None)
    def fail(*args, **kwargs):
        raise RuntimeError("https://example.invalid/?token=private-secret")
    monkeypatch.setattr(module, "install_whisper_model", fail)
    worker = SetupWorker(AppSettings(), tmp_path, "tiny")
    errors = []
    worker.error.connect(errors.append)
    worker.run()
    assert len(errors) == 1 and "private-secret" not in errors[0]


def test_worker_reuses_local_model_without_downloading(tmp_path, monkeypatch):
    from auralwarden.ui import setup_dialog as module
    monkeypatch.setattr(module, "resolve_local_whisper_model", lambda _: tmp_path)
    monkeypatch.setattr(module, "install_whisper_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    worker = SetupWorker(AppSettings(), tmp_path, "tiny")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results == [{"model": str(tmp_path), "speakers": None}]
