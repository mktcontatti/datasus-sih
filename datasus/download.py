# -*- coding: utf-8 -*-
"""Download de uma competencia do SIH/SUS via `pysus`.

Este e o unico modulo do projeto que fala com a rede/pysus. Isolar isso
aqui, atras de uma funcao pura de assinatura simples
(`baixar_competencia(uf, ano, mes) -> ResultadoDownload`), permite
testar todo o resto do pipeline (organizacao, persistencia) sem
precisar de rede.

IMPORTANTE (descoberto comparando com uma fonte de referencia real):
o catalogo S3 usado pela API do pysus (`pysus.ftp.sih`) pode devolver
um arquivo NAO vazio mas PARCIALMENTE INCOMPLETO (menos AIH do que o
arquivo real publicado no FTP oficial do DATASUS). Isso passava
despercebido porque `total_bruto > 0` nesses casos, entao a
competencia era marcada 'sucesso' e nunca reprocessada. Comparando
nosso banco com uma planilha de referencia (91 codigos SIGTAP, ano
completo de 2025): codigos de transplante (grupo "0505") vinham quase
perfeitos, mas codigos de cirurgia cardiaca (grupo "0406") tinham de
14% a 90% de registros faltando, repetindo-se na maioria dos estados.

Por isso, a listagem AO VIVO do FTP oficial (`ftp.datasus.gov.br`)
agora e a PRIMEIRA tentativa, nao um ultimo recurso. A API do pysus
fica como fallback, usada apenas se o FTP direto falhar por um motivo
tecnico.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ResultadoDownload:
    bruto: pd.DataFrame
    total_bruto: int


def _dataframe_de_retorno_pysus(retorno) -> pd.DataFrame:
    """Normaliza os varios formatos de retorno do pysus para um DataFrame."""
    if retorno is None:
        return pd.DataFrame()
    if isinstance(retorno, pd.DataFrame):
        return retorno
    if not isinstance(retorno, (list, tuple)):
        retorno = [retorno]
    partes = []
    for item in retorno:
        if item is None:
            continue
        if isinstance(item, pd.DataFrame):
            partes.append(item)
            continue
        for metodo_nome in ("to_dataframe", "to_pandas"):
            metodo = getattr(item, metodo_nome, None)
            if callable(metodo):
                try:
                    partes.append(metodo())
                    break
                except Exception:
                    pass
        else:
            try:
                partes.append(pd.read_parquet(str(item)))
            except Exception:
                pass
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)

def _decodificar_valor_dbf(valor):
    """Decodifica um valor bruto lido do .dbf (bytes em cp1252)."""
    if isinstance(valor, bytes):
        return valor.decode("cp1252", errors="replace").replace("\x00", "").strip()
    if isinstance(valor, str):
        return valor.replace("\x00", "").strip()
    return valor


def _baixar_via_ftp_direto(uf: str, ano: int, mes: int) -> ResultadoDownload | None:
    """Baixa o arquivo .dbc do grupo RD direto do FTP oficial do DATASUS."""
    import ftplib
    import os
    import tempfile

    from dbfread import DBF
    from pyreaddbc import dbc2dbf

    host = "ftp.datasus.gov.br"
    diretorio = "/dissemin/publicos/SIHSUS/200801_/Dados"
    nome_alvo = f"RD{uf.upper()}{ano % 100:02d}{mes:02d}.dbc".upper()

    ftp = ftplib.FTP(host, timeout=60)
    try:
        ftp.login()
        ftp.set_pasv(True)
        ftp.cwd(diretorio)
        nome_real = next(
            (nome for nome in ftp.nlst() if nome.upper() == nome_alvo), None
        )
        if nome_real is None:
            return None

        caminho_dbc = tempfile.mktemp(suffix=".dbc")
        with open(caminho_dbc, "wb") as arquivo:
            ftp.retrbinary(f"RETR {nome_real}", arquivo.write)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    caminho_dbf = tempfile.mktemp(suffix=".dbf")
    try:
        dbc2dbf(caminho_dbc, caminho_dbf)
        registros = [
            {chave: _decodificar_valor_dbf(valor) for chave, valor in registro.items()}
            for registro in DBF(caminho_dbf, encoding="cp1252", raw=True)
        ]
        df = pd.DataFrame(registros)
    finally:
        for caminho in (caminho_dbc, caminho_dbf):
            try:
                os.remove(caminho)
            except OSError:
                pass

    return ResultadoDownload(bruto=df, total_bruto=len(df))

def baixar_competencia(uf: str, ano: int, mes: int) -> ResultadoDownload:
    """Baixa uma competencia do grupo RD do SIH/SUS.

    Tenta primeiro o FTP oficial direto (bypass total do catalogo do
    pysus). So recorre a API do pysus se o FTP direto falhar por um
    motivo tecnico.
    """
    erros: list[str] = []

    try:
        resultado_ftp = _baixar_via_ftp_direto(uf, ano, mes)
        if resultado_ftp is not None:
            return resultado_ftp
    except Exception as exc:
        erros.append(f"ftp direto: {exc}")

    try:
        import pysus as pysus_mod

        df = pysus_mod.ftp.sih(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except Exception as exc:
        erros.append(f"pysus.ftp.sih (fallback): {exc}")

    if erros:
        raise RuntimeError(
            "Nao foi possivel baixar via pysus. Detalhes: " + " | ".join(erros)
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
