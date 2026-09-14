# -*- coding: utf-8 -*-
"""Pipeline de coleta: baixar → organizar → persistir.

Cada competência (UF + ano/mês de processamento) é processada de ponta
a ponta dentro de uma transação SQLite: se qualquer etapa falhar, nada
fica gravado pela metade.
"""
from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd

from datasus import codigos, settings
from datasus.db import conexao, transacao
from datasus.download import baixar_competencia

COLUNAS_MUNICIPIO_CANDIDATAS = ("MUNIC_MOV", "MUNIC_RES")


# ---------------------------------------------------------------------------
# Geração da lista de competências a coletar
# ---------------------------------------------------------------------------
def competencias_do_periodo(
    ufs: list[str], anos: list[int], meses: list[int]
) -> list[tuple[str, int, int]]:
    """Todas as (uf, ano, mes) do período pedido, exceto competências no
    futuro (que ainda não existem no DATASUS)."""
    hoje = date.today().replace(day=1)
    pares = sorted({(ano, mes) for ano in anos for mes in meses})
    resultado = []
    for uf in ufs:
        for ano, mes in pares:
            if date(ano, mes, 1) <= hoje:
                resultado.append((uf, ano, mes))
    return resultado


# ---------------------------------------------------------------------------
# Organização: filtra pelos códigos monitorados e normaliza campos
# ---------------------------------------------------------------------------
def organizar(
    df_bruto: pd.DataFrame,
    codigos_monitorados: set[str],
    uf: str,
    ano: int,
    mes: int,
) -> pd.DataFrame:
    """Função pura (sem I/O): recebe o DataFrame bruto de uma competência
    e devolve só as linhas cujo procedimento (PROC_REA) está entre os
    monitorados, com os códigos normalizados."""
    colunas_saida = ["uf", "ano", "mes", "n_aih", "cnes", "codigo_sigtap", "municipio_codigo"]
    if df_bruto is None or df_bruto.empty or "PROC_REA" not in df_bruto.columns:
        return pd.DataFrame(columns=colunas_saida)

    df = df_bruto.copy()
    df["codigo_sigtap"] = df["PROC_REA"].apply(lambda v: codigos.normalizar_codigo(v, 10))
    df = df[df["codigo_sigtap"].isin(codigos_monitorados)].copy()
    if df.empty:
        return pd.DataFrame(columns=colunas_saida)

    df["cnes"] = (
        df["CNES"].apply(lambda v: codigos.normalizar_codigo(v, 7))
        if "CNES" in df.columns else None
    )
    df["n_aih"] = df["N_AIH"].astype(str) if "N_AIH" in df.columns else None

    col_municipio = next(
        (c for c in COLUNAS_MUNICIPIO_CANDIDATAS if c in df.columns), None
    )
    df["municipio_codigo"] = (
        df[col_municipio].apply(lambda v: codigos.normalizar_codigo(v, 6))
        if col_municipio else None
    )

    df["uf"] = uf
    df["ano"] = int(ano)
    df["mes"] = int(mes)

    return df[colunas_saida]


# ---------------------------------------------------------------------------
# Persistência (dentro de uma transação já aberta)
# ---------------------------------------------------------------------------
def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _persistir_sucesso(
    conn: sqlite3.Connection,
    uf: str,
    ano: int,
    mes: int,
    organizado: pd.DataFrame,
    total_bruto: int,
) -> None:
    conn.execute(
        "DELETE FROM procedimentos_realizados WHERE uf=? AND ano=? AND mes=?",
        (uf, ano, mes),
    )
    if not organizado.empty:
        linhas = list(
            organizado[["uf", "ano", "mes", "n_aih", "cnes", "codigo_sigtap", "municipio_codigo"]]
            .itertuples(index=False, name=None)
        )
        conn.executemany(
            "INSERT OR REPLACE INTO procedimentos_realizados "
            "(uf, ano, mes, n_aih, cnes, codigo_sigtap, municipio_codigo) "
            "VALUES (?,?,?,?,?,?,?)",
            linhas,
        )

    total_filtrado = len(organizado)
    status = "sucesso" if total_bruto > 0 else "suspeita_falha_silenciosa"
    conn.execute(
        "INSERT INTO competencias "
        "(uf, ano, mes, status, total_bruto, total_filtrado, tentativas, erro, atualizado_em) "
        "VALUES (?,?,?,?,?,?,1,NULL,?) "
        "ON CONFLICT(uf, ano, mes) DO UPDATE SET "
        "  status=excluded.status, total_bruto=excluded.total_bruto, "
        "  total_filtrado=excluded.total_filtrado, "
        "  tentativas=competencias.tentativas + 1, erro=NULL, "
        "  atualizado_em=excluded.atualizado_em",
        (uf, ano, mes, status, total_bruto, total_filtrado, _agora()),
    )


def _persistir_falha(conn: sqlite3.Connection, uf: str, ano: int, mes: int, erro: str) -> None:
    conn.execute(
        "INSERT INTO competencias (uf, ano, mes, status, tentativas, erro, atualizado_em) "
        "VALUES (?,?,?,'falha',1,?,?) "
        "ON CONFLICT(uf, ano, mes) DO UPDATE SET "
        "  status='falha', tentativas=competencias.tentativas + 1, "
        "  erro=excluded.erro, atualizado_em=excluded.atualizado_em",
        (uf, ano, mes, str(erro)[:500], _agora()),
    )


# ---------------------------------------------------------------------------
# Processamento de uma competência, com retry
# ---------------------------------------------------------------------------
def processar_competencia(
    uf: str, ano: int, mes: int, codigos_monitorados: set[str]
) -> tuple[str, int, int, str, str | None]:
    """Baixa, organiza e persiste uma competência. Devolve
    (uf, ano, mes, status, mensagem) para o chamador poder logar."""
    ultimo_erro = None
    for tentativa in range(1, settings.MAX_TENTATIVAS_POR_COMPETENCIA + 1):
        if tentativa > 1:
            time.sleep(settings.PAUSA_ENTRE_TENTATIVAS_SEG)
        try:
            resultado = baixar_competencia(uf, ano, mes)
            organizado = organizar(resultado.bruto, codigos_monitorados, uf, ano, mes)
            with transacao() as conn:
                _persistir_sucesso(conn, uf, ano, mes, organizado, resultado.total_bruto)
            status = "sucesso" if resultado.total_bruto > 0 else "suspeita_falha_silenciosa"
            msg = f"{len(organizado)} registro(s) monitorado(s) de {resultado.total_bruto} no total"
            return uf, ano, mes, status, msg
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = str(exc)

    with transacao() as conn:
        _persistir_falha(conn, uf, ano, mes, ultimo_erro or "erro desconhecido")
    return uf, ano, mes, "falha", ultimo_erro


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def _codigos_monitorados(conn: sqlite3.Connection) -> set[str]:
    linhas = conn.execute(
        "SELECT codigo_sigtap FROM procedimentos WHERE ativo=1"
    ).fetchall()
    codigos_set = {row["codigo_sigtap"] for row in linhas}
    if not codigos_set:
        raise ValueError(
            "Nenhum procedimento ativo encontrado na tabela 'procedimentos'. "
            "Rode `python cli.py importar-procedimentos` primeiro."
        )
    return codigos_set


def _competencias_pendentes(
    conn: sqlite3.Connection, alvo: list[tuple[str, int, int]], forcar: bool
) -> list[tuple[str, int, int]]:
    if forcar:
        return alvo
    linhas = conn.execute(
        "SELECT uf, ano, mes FROM competencias WHERE status='sucesso'"
    ).fetchall()
    ja_ok = {(r["uf"], r["ano"], r["mes"]) for r in linhas}
    return [t for t in alvo if t not in ja_ok]


def rodar_coleta(
    ufs: list[str] | None = None,
    anos: list[int] | None = None,
    meses: list[int] | None = None,
    forcar: bool = False,
    paralelo: int | None = None,
) -> None:
    ufs = ufs or settings.TODAS_UFS
    ano_base = settings.ano_base_atual()
    anos = anos or [ano_base]
    meses = meses or list(range(1, 13))
    paralelo = paralelo or settings.MAX_DOWNLOADS_PARALELOS

    with conexao() as conn:
        codigos_monitorados = _codigos_monitorados(conn)
        alvo = competencias_do_periodo(ufs, anos, meses)
        tarefas = _competencias_pendentes(conn, alvo, forcar)

    print(f"[coleta] Ano-base: {ano_base} | {len(codigos_monitorados)} código(s) "
          f"SIGTAP monitorado(s)")
    print(f"[coleta] {len(tarefas)}/{len(alvo)} competência(s) a processar "
          f"({len(alvo) - len(tarefas)} já concluída(s) com sucesso).")

    if not tarefas:
        print("[coleta] Nada a fazer.")
        return

    concluidas = 0
    with ThreadPoolExecutor(max_workers=paralelo) as executor:
        futuros = {
            executor.submit(processar_competencia, uf, ano, mes, codigos_monitorados): (uf, ano, mes)
            for uf, ano, mes in tarefas
        }
        for futuro in as_completed(futuros):
            uf, ano, mes, status, msg = futuro.result()
            concluidas += 1
            print(f"[{concluidas}/{len(tarefas)}] {uf} {ano}/{mes:02d}: {status} -- {msg}")

    print("[coleta] Concluído.")


def retentar_falhas(paralelo: int | None = None) -> None:
    """Reprocessa competências marcadas como 'falha' ou
    'suspeita_falha_silenciosa'."""
    paralelo = paralelo or settings.MAX_DOWNLOADS_PARALELOS
    with conexao() as conn:
        codigos_monitorados = _codigos_monitorados(conn)
        linhas = conn.execute(
            "SELECT uf, ano, mes FROM competencias "
            "WHERE status IN ('falha', 'suspeita_falha_silenciosa')"
        ).fetchall()
    tarefas = [(r["uf"], r["ano"], r["mes"]) for r in linhas]

    if not tarefas:
        print("[coleta] Nenhuma falha ou suspeita pendente de nova tentativa.")
        return

    print(f"[coleta] Retentando {len(tarefas)} competência(s)...")
    concluidas = 0
    with ThreadPoolExecutor(max_workers=paralelo) as executor:
        futuros = {
            executor.submit(processar_competencia, uf, ano, mes, codigos_monitorados): (uf, ano, mes)
            for uf, ano, mes in tarefas
        }
        for futuro in as_completed(futuros):
            uf, ano, mes, status, msg = futuro.result()
            concluidas += 1
            print(f"[{concluidas}/{len(tarefas)}] {uf} {ano}/{mes:02d}: {status} -- {msg}")
    print("[coleta] Retentativa concluída.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_meses(valor: str) -> list[int]:
    if "-" in valor:
        ini, fim = valor.split("-")
        return list(range(int(ini), int(fim) + 1))
    return [int(x) for x in valor.split(",")]
