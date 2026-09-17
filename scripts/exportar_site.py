# -*- coding: utf-8 -*-
"""Exporta o dataset do painel para um JSON estatico consumido pelo site
em docs/ (GitHub Pages). Roda localmente / no Codespace, nunca em CI.

Uso:
    python scripts/exportar_site.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from datasus import consultas, settings
from datasus.db import inicializar_banco

FUSO_BR = ZoneInfo("America/Sao_Paulo")
SAIDA = Path(__file__).resolve().parent.parent / "docs" / "data.json"


def main() -> None:
    inicializar_banco()
    ano_base = settings.ano_base_atual()
    df = consultas.dataset_ano(ano_base)
    cobertura = consultas.relatorio_cobertura(ano_base)
    ultima_comp = consultas.ultima_competencia_coletada(ano_base)

    if df.empty:
        raise SystemExit("Dataset vazio para o ano-base atual; nada a exportar.")

    estabelecimentos = (
        df.groupby("cnes")
        .agg(
            razao_social=("razao_social", "first"),
            nome_fantasia=("nome_fantasia", "first"),
            municipio_nome=("municipio_nome", "first"),
            uf=("uf", "first"),
            regiao=("regiao", "first"),
        )
        .reset_index()
        .to_dict(orient="records")
    )
    estabelecimentos = {e["cnes"]: e for e in estabelecimentos}
    for e in estabelecimentos.values():
        del e["cnes"]

    fatos = (
        df.groupby(["cnes", "categoria", "tipo", "mes"])
        .size()
        .reset_index(name="qtd")
        .to_dict(orient="records")
    )

    categorias_cirurgia = sorted(
        df.loc[df["tipo"] == "Cirurgia", "categoria"].dropna().unique().tolist()
    )
    categorias_transplante = sorted(
        df.loc[df["tipo"] == "Transplante", "categoria"].dropna().unique().tolist()
    )

    texto_cobertura = None
    if ultima_comp:
        _, mes_ult = ultima_comp
        texto_cobertura = f"Dados até {settings.MESES_NOME_LONGO[mes_ult - 1]} de {ano_base}"

    saida = {
        "gerado_em": datetime.now(FUSO_BR).strftime("%d/%m/%Y às %H:%M"),
        "ano_base": ano_base,
        "texto_cobertura": texto_cobertura,
        "competencias_faltantes": len(cobertura["faltantes"]),
        "categorias_cirurgia": categorias_cirurgia,
        "categorias_transplante": categorias_transplante,
        "estabelecimentos": estabelecimentos,
        "fatos": fatos,
    }

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(
        json.dumps(saida, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[exportar_site] {len(estabelecimentos)} estabelecimento(s), {len(fatos)} fato(s) -> {SAIDA}")


if __name__ == "__main__":
    main()
