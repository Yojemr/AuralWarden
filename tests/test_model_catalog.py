from pathlib import Path

from auralwarden import model_catalog


def _create_model(path: Path) -> Path:
    path.mkdir(parents=True)
    for name in model_catalog.MODEL_MARKERS:
        (path / name).write_text("test", encoding="utf-8")
    return path


def test_catalog_discovers_and_prioritizes_large_v3_turbo(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "models"
    base = _create_model(root / "base")
    turbo = _create_model(root / "large-v3-turbo")
    monkeypatch.setattr(model_catalog, "model_search_roots", lambda: (root,))
    monkeypatch.setattr(model_catalog, "_hugging_face_hub_roots", lambda: ())

    models = model_catalog.discover_local_whisper_models()

    assert [item.path for item in models] == [turbo, base]
    assert model_catalog.resolve_local_whisper_model("large-v3-turbo", models) == turbo
    assert model_catalog.resolve_local_whisper_model("auto", models) == turbo
    assert (
        model_catalog.resolve_local_whisper_model(
            r"D:\ubicacion-anterior\data\models\large-v3-turbo", models
        )
        == turbo
    )


def test_search_roots_include_project_data_for_versioned_executable(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "AuralWarden"
    executable_root = project / "outputs" / "AuralWarden-0.2.1"
    executable_root.mkdir(parents=True)
    project_models = project / "data" / "models"
    monkeypatch.setattr(model_catalog, "application_root", lambda: executable_root)
    monkeypatch.setattr(model_catalog, "data_dir", lambda: executable_root / "data")

    roots = model_catalog.model_search_roots()

    assert project_models.resolve() in roots
