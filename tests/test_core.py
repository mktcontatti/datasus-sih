import pandas as pd
from datasus.codigos import normalizar_codigo
from datasus.coleta import organizar, competencias_do_periodo, parse_meses
from datasus.db import conexao, transacao
from datasus import consultas


def test_normalizacao_preserva_zeros():
    assert normalizar_codigo("2078", 7) == "0002078"
    assert normalizar_codigo(505020092.0, 10) == "0505020092"


def test_organizar_filtra_e_normaliza():
    bruto = pd.DataFrame([{"PROC_REA": "0505020092", "N_AIH": "A1", "CNES": 2078, "MUNIC_MOV": 431490}])
    df = organizar(bruto, {"0505020092"}, "RS", 2025, 1)
    assert len(df) == 1
    assert df.iloc[0]["cnes"] == "0002078"
    assert df.iloc[0]["municipio_codigo"] == "431490"


def test_parse_meses():
    assert parse_meses("1-3") == [1, 2, 3]
    assert parse_meses("1,3,5") == [1, 3, 5]


def test_transacao_rollback():
    try:
        with transacao() as conn:
            conn.execute("INSERT INTO procedimentos (codigo_sigtap, ativo) VALUES ('X',1)")
            raise ValueError("falha")
    except ValueError:
        pass
    with conexao() as conn:
        assert conn.execute("SELECT COUNT(*) FROM procedimentos WHERE codigo_sigtap='X'").fetchone()[0] == 0


def test_diagnostico_vazio():
    r = consultas.relatorio_diagnostico()
    assert r["procedimentos"] == 0
    assert r["cnes_sem_nome"] == 0
