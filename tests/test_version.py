from pathlib import Path
import tomllib

from auralwarden import __version__


def test_release_version_is_consistent():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == (root / "VERSION").read_text().strip() == metadata["project"]["version"]
