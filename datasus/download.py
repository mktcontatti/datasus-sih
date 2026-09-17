# -*- coding: utf-8 -*-
"""Download de uma competencia do SIH/SUS via `pysus`.

Este e o unico modulo do projeto que fala com a rede/pysus. Isolar isso
aqui, atras de uma funcao pura de assinatura simples
(`baixar_competencia(uf, ano, mes) -> ResultadoDownload`), permite
testar todo o resto do pipeline (organizacao, persistencia) sem
precisar de rede.

IMPORTANTE (descoberto com a Dataglass, confirmado no TABNET): o grupo
"RD" (AIH Reduzida) NAO e o problema de fonte incompleta que se pensava
antes -- tanto o catalogo do pysus quanto o FTP direto trazem os MESMOS
dados de RD. O problema real e que o grupo RD resume cada AIH em UMA
linha, com apenas o PROCEDIMENTO PRINCIPAL daquela internacao. Cirurgias
que acontecem como procedimento SECUNDARIO de uma AIH (comum em cirurgia
cardiovascular, onde e frequente uma AIH ter mais de um procedimento
cirurgico) nunca aparecem no RD.

O grupo "SP" (Servicos Profissionais) resolve isso: e o detalhe por
servico/procedimento de cada AIH, com uma linha por procedimento
realizado (nao so o principal). Por isso agora baixamos SP como fonte
principal, normal e simplesmente renomeamos as colunas SP_* para os
mesmos nomes que o RD usa (PROC_REA, CNES, N_AIH, MUNIC_MOV, MUNIC_RES)
para que o resto do pipeline (`datasus/coleta.py:organizar`) nao
precise saber a diferenca entre as duas fontes.

Confirmado comparando com o TABNET (Dados Detalhados das AIH, por local
de internacao) e com a metodologia da Dataglass: para o procedimento
"Revascularizacao Miocardica C/ Uso de Extracorporea (C/ 2 ou Mais
Enxertos)" em SP, outubro/2025 -- RD (so principal) da 371, SP (todos
os procedimentos da AIH) da 401, que e o numero que bate com a
planilha de referencia.

`ResultadoDownload.total_bruto` guarda quantas linhas vieram no arquivo
ANTES de qualquer filtro pelos codigos SIGTAP monitorados (no grupo SP,
isso e o total de linhas de servico/procedimento, nao de AIH). Isso
permite diferenciar, no pipeline de coleta, um mes em que legitimamente
nao houve nenhum procedimento monitorado (total_bruto > 0) de uma falha
de download que retornou vazio (total_bruto == 0) -- ver
`datasus/coleta.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

GRUPO_PADRAO = "SP"

# Colunas do grupo SP que sao renomeadas para os nomes equivalentes do
# grupo RD, para que `datasus/coleta.py:organizar` funcione sem mudanca
# nenhuma nos dois grupos.
RENOMEIO_COLUNAS_SP = {
    "SP_PROCREA": "PROC_REA",
    "SP_CNES": "CNES",
    "SP_NAIH": "N_AIH",
    "SP_M_HOSP": "MUNIC_MOV",
    "SP_M_PAC": "MUNIC_RES",
}


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

def _baixar_via_ftp_direto(
    uf: str, ano: int, mes: int, grupo: str = GRUPO_PADRAO
) -> ResultadoDownload | None:
    """Baixa o arquivo .dbc de um grupo do SIH/SUS direto do FTP oficial."""
    import ftplib
    import os
    import tempfile

    from dbfread import DBF
    from pyreaddbc import dbc2dbf

    host = "ftp.datasus.gov.br"
    diretorio = "/dissemin/publicos/SIHSUS/200801_/Dados"
    nome_alvo = f"{grupo}{uf.upper()}{ano % 100:02d}{mes:02d}.dbc".upper()

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

    if grupo == "SP":
        df = df.rename(columns=RENOMEIO_COLUNAS_SP)

    return ResultadoDownload(bruto=df, total_bruto=len(df))


def baixar_competencia(uf: str, ano: int, mes: int) -> ResultadoDownload:
    """Baixa uma competencia do SIH/SUS.

    Tenta primeiro o FTP oficial direto do grupo SP (Servicos
    Profissionais), que traz todos os procedimentos de cada AIH -- nao
    so o principal, ao contrario do grupo RD (ver nota no topo do
    modulo). So recorre a API do pysus se o FTP direto falhar por um
    motivo tecnico.
    """
    erros: list[str] = []

    try:
        resultado_ftp = _baixar_via_ftp_direto(uf, ano, mes, grupo=GRUPO_PADRAO)
        if resultado_ftp is not None:
            return resultado_ftp
    except Exception as exc:
        erros.append(f"ftp direto ({GRUPO_PADRAO}): {exc}")

    try:
        import pysus as pysus_mod

        df = pysus_mod.ftp.sih(state=uf, year=ano, month=mes, group=GRUPO_PADRAO, as_dataframe=True)
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.rename(columns=RENOMEIO_COLUNAS_SP)
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except Exception as exc:
        erros.append(f"pysus.ftp.sih (fallback): {exc}")

    if erros:
        raise RuntimeError(
            "Nao foi possivel baixar via pysus. Detalhes: " + " | ".join(erros)
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
