import pytest


@pytest.fixture(autouse=True)
def isolated_application_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AURALWARDEN_DATA_DIR", str(tmp_path / "synthetic-app-data"))
