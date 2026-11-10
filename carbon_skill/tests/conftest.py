import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No network, no real data folder."""
    monkeypatch.setenv("CARBON_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("CARBON_COUNTRY", "NLD")
