# -*- coding: utf-8 -*-
"""Download de uma competencia do SIH/SUS via `pysus`.

Este e o unico modulo do projeto que fala com a rede/pysus. Isolar isso
aqui, atras de uma funcao pura de assinatura simples
(`baixar_competencia(uf, ano, mes) -> ResultadoDownload`), permite
testar todo o resto do pipeline (organizacao, persistencia) sem
precisar de rede -- basta trocar esta funcao por um duble nos testes.

A API namespaced moderna do pysus (`pysus.ftp.sih`) e priorizada sobre
a funcao legada (`pysus.sih`), por ser a forma atualmente recomendada
pela biblioteca. Por padrao essa API consulta um espelho em nuvem
mantido pelos mantenedores do pysus; quando o resultado vem vazio, uma
segunda tentativa forca a consulta direta ao servidor oficial do
DATASUS (`source="origin"`) antes de recorrer a API legada como ultimo
recurso.

`ResultadoDownload.total_bruto` guarda quantas AIH vieram no arquivo
ANTES de qualquer filtro pelos codigos SIGTAP monitorados. Isso permite
diferenciar, no pipeline de coleta, um mes em que legitimamente nao
houve nenhum procedimento monitorado (total_bruto > 0) de uma falha de
download que retornou vazio (total_bruto == 0) -- ver `datasus/coleta.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

@dataclass
class ResultadoDownload:
    bruto: pd.DataFrame       # todas as AIH da competencia (grupo RD), sem filtro
    total_bruto: int

def _dataframe_de_retorno_pysus(retorno) -> pd.DataFrame:
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

def baixar_competencia(uf: str, ano: int, mes: int) -> ResultadoDownload:
    erros: list[str] = []

    try:
        import pysus as pysus_mod

        df = pysus_mod.ftp.sih(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except Exception as exc:
        erros.append(f"pysus.ftp.sih(source=catalog): {exc}")

    try:
        import pysus as pysus_mod

        df = pysus_mod.ftp.sih(
            state=uf, year=ano, month=mes, group="RD",
            source="origin", as_dataframe=True,
        )
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except TypeError as exc:
        erros.append(f"pysus.ftp.sih(source=origin): parametro nao suportado ({exc})")
    except Exception as exc:
        erros.append(f"pysus.ftp.sih(source=origin): {exc}")

    try:
        from pysus import sih as sih_func

        try:
            df = _dataframe_de_retorno_pysus(
                sih_func(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
            )
            if isinstance(df, pd.DataFrame) and not df.empty:
                return ResultadoDownload(bruto=df, total_bruto=len(df))
        except TypeError as exc:
            erros.append(f"pysus.sih(group=RD): parametro nao suportado ({exc})")
    except ImportError as exc:
        erros.append(f"import pysus.sih: {exc}")

    if erros:
        raise RuntimeError(
            "Nao foi possivel baixar via pysus. Detalhes: " + " | ".join(erros[-3:])
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
