# -*- coding: utf-8 -*-
"""Importação do catálogo de procedimentos monitorados (SIGTAP).

A lista de códigos SIGTAP a monitorar vive em `data/procedimentos.xlsx`
(uma planilha simples) e é importada para dentro do banco por este
módulo. Depois de importado, o resto do sistema nunca mais precisa
reabrir o Excel — só consulta a tabela `procedimentos`.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from datasus import settings
from datasus.codigos import normalizar_codigo
from datasus.db import transacao

COLUNAS_ESPERADAS = [
    "Codigo_SIGTAP", "Descricao_SIGTAP", "Grupo_Proc", "Subgrupo_Proc",
    "Categoria", "Tipo_TX_CC", "Ativo",
]


def importar_xlsx(caminho: Path | None = None) -> int:
    """Lê `data/procedimentos.xlsx` (aba "Procedimentos") e sincroniza a
    tabela `procedimentos` no banco. Devolve quantos códigos ficaram
    marcados como ativos."""
    caminho = caminho or settings.PROCEDIMENTOS_XLSX
    if not caminho.exists():
        raise FileNotFoundError(
            f"Não encontrei {caminho}. Crie essa planilha com as colunas "
            f"{COLUNAS_ESPERADAS} antes de importar."
        )

    df = pd.read_excel(caminho, sheet_name="Procedimentos", dtype={"Codigo_SIGTAP": str})
    faltando = [c for c in COLUNAS_ESPERADAS if c not in df.columns]
    if faltando:
        raise ValueError(f"Coluna(s) faltando em {caminho.name}: {faltando}")

    df["Codigo_SIGTAP"] = df["Codigo_SIGTAP"].apply(lambda v: normalizar_codigo(v, 10))
    df = df.dropna(subset=["Codigo_SIGTAP"])
    df["ativo"] = (
        df["Ativo"].astype(str).str.strip().str.lower().isin(("sim", "true", "1"))
    ).astype(int)

    linhas = list(df[[
        "Codigo_SIGTAP", "Descricao_SIGTAP", "Grupo_Proc", "Subgrupo_Proc",
        "Categoria", "Tipo_TX_CC", "ativo",
    ]].itertuples(index=False, name=None))

    with transacao() as conn:
        conn.executemany(
            "INSERT INTO procedimentos "
            "(codigo_sigtap, descricao, grupo, subgrupo, categoria, tipo, ativo) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(codigo_sigtap) DO UPDATE SET "
            "  descricao=excluded.descricao, grupo=excluded.grupo, "
            "  subgrupo=excluded.subgrupo, categoria=excluded.categoria, "
            "  tipo=excluded.tipo, ativo=excluded.ativo",
            linhas,
        )

    ativos = int(df["ativo"].sum())
    print(f"[catalogo] {len(df)} procedimento(s) importado(s) ({ativos} ativo(s)).")
    return ativos
