from datasus import estabelecimentos

class Resposta:
    def raise_for_status(self): pass
    def json(self):
        return {"estabelecimentos": [{"codigo_cnes": "0002078", "nome_razao_social": "Hospital Correto", "nome_fantasia": "HC"}]}


def test_busca_direta_confere_cnes(monkeypatch):
    monkeypatch.setattr(estabelecimentos.requests, "get", lambda *a, **k: Resposta())
    assert estabelecimentos._buscar_direto("0002078") == ("Hospital Correto", "HC")


def test_busca_direta_rejeita_outro_cnes(monkeypatch):
    class Outra(Resposta):
        def json(self): return {"estabelecimentos": [{"codigo_cnes": "9999999", "nome_fantasia": "Errado"}]}
    monkeypatch.setattr(estabelecimentos.requests, "get", lambda *a, **k: Outra())
    assert estabelecimentos._buscar_direto("0002078") is None
