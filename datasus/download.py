# -*- coding: utf-8 -*-
"""Download de uma competência do SIH/SUS via `pysus`.

Este é o único módulo do projeto que fala com a rede/pysus. Isolar isso
aqui, atrás de uma função pura de assinatura simples
(`baixar_competencia(uf, ano, mes) -> ResultadoDownload`), permite
testar todo o resto do pipeline (organização, persistência) sem
precisar de rede — basta trocar esta função por um dublê nos testes.

A API namespaced moderna do pysus (`pysus.ftp.sih`) é priorizada sobre
a função legada (`pysus.sih`), por ser a forma atualmente recomendada
pela biblioteca. Por padrão essa API consulta um espelho em nuvem
mantido pelos mantenedores do pysus; quando o resultado vem vazio, uma
segunda tentativa força a consulta direta ao servidor oficial do
DATASUS (`source="origin"`) antes de recorrer à API legada como último
recurso.

IMPORTANTE (descoberto investigando lacunas reais de dados): mesmo
`source="origin"` do pysus descobre QUAIS arquivos existem consultando
o mesmo índice/catálogo S3 (`pysus.query(...)`) — só muda de onde baixa
os bytes depois de decidir que o arquivo existe (ver
`pysus/api/_impl/source.py::_fetch_origin_direct`). Esse catálogo é um
índice mantido manualmente pelos mantenedores do pysus e pode ter
lacunas (o próprio changelog do pysus tem um comando interno de
"sync and check databases on s3"), mesmo quando o arquivo existe de
verdade no FTP oficial do DATASUS. Por isso, como último recurso
verdadeiramente independente do pysus, `_baixar_via_ftp_direto` faz uma
listagem AO VIVO do FTP oficial (`ftp.datasus.gov.br`) — o mesmo padrão
usado pelo pacote de referência `microdatasus` (R) — e decodifica o
`.dbc` encontrado com `pyreaddbc` (a mesma biblioteca que o pysus usa
por baixo). Só quando essa listagem ao vivo confirma que o arquivo não
existe é que a competência é tratada como genuinamente vazia.

`ResultadoDownload.total_bruto` guarda quantas AIH vieram no arquivo
ANTES de qualquer filtro pelos códigos SIGTAP monitorados. Isso permite
diferenciar, no pipeline de coleta, um mês em que legitimamente não
houve nenhum procedimento monitorado (total_bruto > 0) de uma falha de
download que retornou vazio (total_bruto == 0) — ver `datasus/coleta.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ResultadoDownload:
    bruto: pd.DataFrame       # todas as AIH da competência (grupo RD), sem filtro
    total_bruto: int


def _dataframe_de_retorno_pysus(retorno) -> pd.DataFrame:
    """Normaliza os vários formatos de retorno que diferentes versões do
    pysus podem devolver (DataFrame direto, objeto com .to_dataframe(),
    lista de parquets, etc.) para um único pd.DataFrame."""
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
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                partes.append(pd.read_parquet(str(item)))
            except Exception:  # noqa: BLE001
                pass
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


def _baixar_via_ftp_direto(uf: str, ano: int, mes: int) -> ResultadoDownload | None:
    """Baixa o arquivo .dbc do grupo RD direto do FTP oficial do DATASUS,
    sem depender do catálogo do pysus (ver nota no topo do módulo).

    Devolve `None` quando a listagem AO VIVO do diretório confirma que o
    arquivo não existe (competência genuinamente sem dado publicado).
    Levanta exceção em caso de falha de rede/FTP — o chamador decide o
    que fazer (registrar como erro comum, tentar de novo, etc.)."""
    import ftplib
    import os
    import tempfile

    import pyreaddbc

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

        caminho_tmp = tempfile.mktemp(suffix=".dbc")
        with open(caminho_tmp, "wb") as arquivo:
            ftp.retrbinary(f"RETR {nome_real}", arquivo.write)
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()

    try:
        df = pyreaddbc.read_dbc(caminho_tmp, encoding="iso-8859-1")
    finally:
        try:
            os.remove(caminho_tmp)
        except OSError:
            pass

    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return ResultadoDownload(bruto=df, total_bruto=len(df))


def baixar_competencia(uf: str, ano: int, mes: int) -> ResultadoDownload:
    """Baixa uma competência do grupo RD (AIH Reduzida) do SIH/SUS.

    Tenta, em ordem, até encontrar dados: API moderna (espelho padrão),
    API moderna (servidor oficial), API legada e, por fim, FTP oficial
    direto (bypass total do catálogo do pysus). Levanta `RuntimeError`
    apenas se todas as tentativas falharem com exceção; se todas
    devolverem vazio sem erro (incluindo a listagem ao vivo do FTP
    confirmando ausência do arquivo), retorna um resultado com
    `total_bruto=0`.
    """
    erros: list[str] = []

    try:
        import pysus as pysus_mod  # type: ignore

        df = pysus_mod.ftp.sih(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except Exception as exc:  # noqa: BLE001
        erros.append(f"pysus.ftp.sih(source=catalog): {exc}")

    try:
        import pysus as pysus_mod  # type: ignore

        df = pysus_mod.ftp.sih(
            state=uf, year=ano, month=mes, group="RD",
            source="origin", as_dataframe=True,
        )
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except TypeError as exc:
        erros.append(f"pysus.ftp.sih(source=origin): parâmetro não suportado ({exc})")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"pysus.ftp.sih(source=origin): {exc}")

    try:
        from pysus import sih as sih_func  # type: ignore

        try:
            df = _dataframe_de_retorno_pysus(
                sih_func(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
            )
            if isinstance(df, pd.DataFrame) and not df.empty:
                return ResultadoDownload(bruto=df, total_bruto=len(df))
        except TypeError as exc:
            erros.append(f"pysus.sih(group=RD): parâmetro não suportado ({exc})")
    except ImportError as exc:
        erros.append(f"import pysus.sih: {exc}")

    try:
        resultado_ftp = _baixar_via_ftp_direto(uf, ano, mes)
        if resultado_ftp is not None:
            return resultado_ftp
    except Exception as exc:  # noqa: BLE001
        erros.append(f"ftp direto (bypass catálogo pysus): {exc}")

    if erros:
        raise RuntimeError(
            "Não foi possível baixar via pysus. Detalhes: " + " | ".join(erros[-3:])
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
