import pytest
from datasus import settings
from datasus.db import inicializar_banco

@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(settings, "DB_PATH", caminho)
    inicializar_banco()
    yield caminho
