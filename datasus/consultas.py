# -*- coding: utf-8 -*-
"""Consultas de leitura usadas pelo painel (app.py) e pelos relatórios.

Todo o enriquecimento (nome do estabelecimento, nome do município,
descrição/categoria do procedimento) acontece aqui, via JOIN em SQL, na
hora da consulta — nunca é gravado junto com o dado bruto.
"""
from __future__ import annotations

import pandas as pd

from datasus import settings
from datasus.db import conexao

_QUERY_DATASET = """
    SELECT
        pr.uf, pr.ano, pr.mes,
        pr.cnes, pr.codigo_sigtap, pr.n_aih,
        p.descricao   AS descricao_sigtap,
        p.categoria   AS categoria,
        p.tipo        AS tipo,
        e.razao_social,
        e.nome_fantasia,
        m.nome        AS municipio_nome
    FROM procedimentos_realizados pr
    LEFT JOIN procedimentos     p ON p.codigo_sigtap = pr.codigo_sigtap
    LEFT JOIN estabelecimentos  e ON e.cnes = pr.cnes
    LEFT JOIN municipios        m ON m.codigo_ibge = pr.municipio_codigo
    WHERE pr.ano = ?
"""


def dataset_ano(ano: int) -> pd.DataFrame:
    """Dataset completo (já enriquecido) para um ano de competência
    específico — a unidade que o painel e os relatórios consomem."""
    with conexao() as conn:
        df = pd.read_sql_query(_QUERY_DATASET, conn, params=(ano,))
    if df.empty:
        return df
    df["regiao"] = df["uf"].map(settings.REGIAO_POR_UF)
    df["estabelecimento"] = df["nome_fantasia"].fillna(df["razao_social"]).fillna("Não disponível")
    df["municipio_nome"] = df["municipio_nome"].fillna("Não disponível")
    df["razao_social"] = df["razao_social"].fillna("Não disponível")
    df["nome_fantasia"] = df["nome_fantasia"].fillna("Não disponível")
    df["categoria"] = df["categoria"].fillna("Não classificado")
    df["tipo"] = df["tipo"].fillna("Não classificado")
    return df


def relatorio_cobertura(ano_base: int) -> dict:
    """Cobertura do ano-base: quantas das 12 competências × todas as UFs
    já foram coletadas com sucesso."""
    with conexao() as conn:
        linhas = conn.execute(
            "SELECT uf, ano, mes, status FROM competencias WHERE ano = ?",
            (ano_base,),
        ).fetchall()

    concluidas = {
        (r["uf"], r["mes"]) for r in linhas
        if r["status"] in ("sucesso", "suspeita_falha_silenciosa")
    }
    suspeitas = {(r["uf"], r["mes"]) for r in linhas if r["status"] == "suspeita_falha_silenciosa"}
    falhas = {(r["uf"], r["mes"]) for r in linhas if r["status"] == "falha"}

    esperado = {(uf, mes) for uf in settings.TODAS_UFS for mes in range(1, 13)}
    faltantes = sorted(esperado - concluidas)

    return {
        "ano_base": ano_base,
        "esperado": len(esperado),
        "concluido": len(concluidas),
        "faltantes": faltantes,
        "percentual": (len(concluidas) / len(esperado)) if esperado else 1.0,
        "suspeitas_falha_silenciosa": sorted(suspeitas),
        "falhas": sorted(falhas),
    }


def ultima_competencia_coletada(ano_base: int) -> tuple[int, int] | None:
    """Devolve (ano, mês) da competência mais recente com status
    'sucesso' dentro do ano-base, ou None se nada foi coletado ainda.
    Usada para exibir 'atualizado até <mês> de <ano>' no painel."""
    with conexao() as conn:
        linha = conn.execute(
            "SELECT ano, mes FROM competencias "
            "WHERE ano = ? AND status = 'sucesso' "
            "ORDER BY mes DESC LIMIT 1",
            (ano_base,),
        ).fetchone()
    if linha is None:
        return None
    return linha["ano"], linha["mes"]


def relatorio_integridade() -> pd.DataFrame:
    """Reconcilia `competencias.total_filtrado` (o que ficou registrado
    como coletado) contra a contagem real em `procedimentos_realizados`.
    Com a persistência em SQLite (transação única cobrindo download +
    organização + gravação), essas duas contagens devem sempre bater;
    esta consulta serve como verificação contínua de integridade."""
    with conexao() as conn:
        controle = pd.read_sql_query(
            "SELECT uf, ano, mes, total_filtrado, status FROM competencias "
            "WHERE status IN ('sucesso', 'suspeita_falha_silenciosa')",
            conn,
        )
        real = pd.read_sql_query(
            "SELECT uf, ano, mes, COUNT(*) AS total_real "
            "FROM procedimentos_realizados GROUP BY uf, ano, mes",
            conn,
        )
    if controle.empty:
        return pd.DataFrame(columns=["uf", "ano", "mes", "total_filtrado", "total_real"])

    comparado = controle.merge(real, on=["uf", "ano", "mes"], how="left")
    comparado["total_real"] = comparado["total_real"].fillna(0).astype(int)
    divergentes = comparado[comparado["total_filtrado"] != comparado["total_real"]]
    return divergentes.sort_values(["uf", "ano", "mes"]).reset_index(drop=True)


def relatorio_diagnostico() -> dict:
    """Indicadores objetivos de qualidade do banco atual."""
    with conexao() as conn:
        def valor(sql):
            return int(conn.execute(sql).fetchone()[0])
        return {
            "procedimentos": valor("SELECT COUNT(*) FROM procedimentos_realizados"),
            "cnes_distintos": valor("SELECT COUNT(DISTINCT cnes) FROM procedimentos_realizados WHERE cnes IS NOT NULL AND cnes<>''"),
            "cnes_sem_nome": valor("""SELECT COUNT(DISTINCT pr.cnes) FROM procedimentos_realizados pr
                LEFT JOIN estabelecimentos e ON e.cnes=pr.cnes WHERE pr.cnes IS NOT NULL AND pr.cnes<>''
                AND (e.cnes IS NULL OR (e.razao_social IS NULL AND e.nome_fantasia IS NULL))"""),
            "municipios_sem_nome": valor("""SELECT COUNT(DISTINCT pr.municipio_codigo) FROM procedimentos_realizados pr
                LEFT JOIN municipios m ON m.codigo_ibge=pr.municipio_codigo
                WHERE pr.municipio_codigo IS NOT NULL AND pr.municipio_codigo<>'' AND m.codigo_ibge IS NULL"""),
            "codigos_fora_catalogo": valor("""SELECT COUNT(DISTINCT pr.codigo_sigtap) FROM procedimentos_realizados pr
                LEFT JOIN procedimentos p ON p.codigo_sigtap=pr.codigo_sigtap WHERE p.codigo_sigtap IS NULL"""),
            "competencias_com_falha": valor("SELECT COUNT(*) FROM competencias WHERE status='falha'"),
            "competencias_suspeitas": valor("SELECT COUNT(*) FROM competencias WHERE status='suspeita_falha_silenciosa'"),
        }
