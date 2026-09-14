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


def baixar_competencia(uf: str, ano: int, mes: int) -> ResultadoDownload:
    """Baixa uma competência do grupo RD (AIH Reduzida) do SIH/SUS.

    Tenta, em ordem, até encontrar dados: API moderna (espelho padrão),
    API moderna (servidor oficial) e API legada. Levanta `RuntimeError`
    apenas se todas as tentativas falharem com exceção; se todas
    devolverem vazio sem erro, retorna um resultado com `total_bruto=0`.
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

        for kwargs in (
            dict(state=uf, year=ano, month=mes, group="RD", as_dataframe=True),
            dict(state=uf, year=ano, month=mes, groups="RD", as_dataframe=True),
        ):
            try:
                df = _dataframe_de_retorno_pysus(sih_func(**kwargs))
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return ResultadoDownload(bruto=df, total_bruto=len(df))
            except TypeError as exc:
                erros.append(f"pysus.sih({kwargs}): {exc}")
    except ImportError as exc:
        erros.append(f"import pysus.sih: {exc}")

    if erros:
        raise RuntimeError(
            "Não foi possível baixar via pysus. Detalhes: " + " | ".join(erros[-3:])
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
