# -*- coding: utf-8 -*-
"""Download de uma competência do SIH/SUS via `pysus`.

Este é o único módulo do projeto que fala com a rede/pysus. Isolar isso
aqui, atrás de uma função pura de assinatura simples
(`baixar_competencia(uf, ano, mes) -> ResultadoDownload`), permite
testar todo o resto do pipeline (organização, persistência) sem
precisar de rede — basta trocar esta função por um dublê nos testes.

A API namespaced moderna do pysus (`pysus.ftp.sih`) é a forma
atualmente recomendada pela biblioteca e é usada como primeira
tentativa. Ela consulta um índice/catálogo S3 mantido pelos
mantenedores do pysus para descobrir quais arquivos existem.

IMPORTANTE (descoberto investigando lacunas reais de dados): esse
catálogo pode ter lacunas mesmo quando o arquivo existe de verdade no
FTP oficial do DATASUS — o próprio changelog do pysus tem um comando
interno de "sync and check databases on s3", confirmando que ele exige
sincronização manual periódica pelos mantenedores. Duas variações que
pareciam hedges úteis (`pysus.ftp.sih(source="origin")` e a função
legada `pysus.sih()`) foram removidas daqui: ambas descobrem QUAIS
arquivos existem consultando esse MESMO catálogo internamente (ver
`pysus/api/_impl/source.py::_fetch_origin_direct` — `source="origin"`
só muda de onde baixa os bytes depois de já ter decidido, via catálogo,
que o arquivo existe), então nunca teriam sucesso nos casos em que a
tentativa via catálogo padrão falha por essa razão — eram complexidade
sem cobertura real adicional.

Como último recurso genuinamente independente do catálogo do pysus,
`_baixar_via_ftp_direto` faz uma listagem AO VIVO do FTP oficial
(`ftp.datasus.gov.br`) — o mesmo padrão usado pelo pacote de referência
`microdatasus` (R) — baixa o `.dbc` encontrado e o decodifica com as
mesmas ferramentas que o pysus usa internamente: `pyreaddbc.dbc2dbf`
converte o `.dbc` para `.dbf` (pyreaddbc não expõe leitura direta para
DataFrame nesta versão, apesar do que sugere seu README) e
`dbfread.DBF` lê o `.dbf` resultante. Só quando a listagem ao vivo
confirma que o arquivo não existe é que a competência é tratada como
genuinamente vazia.

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


def _decodificar_valor_dbf(valor):
    """Decodifica um valor bruto lido do .dbf (bytes em cp1252, às vezes
    terminado com bytes NUL de preenchimento) para uma string limpa —
    mesma lógica que o próprio pysus aplica internamente."""
    if isinstance(valor, bytes):
        return valor.decode("cp1252", errors="replace").replace("\x00", "").strip()
    if isinstance(valor, str):
        return valor.replace("\x00", "").strip()
    return valor


def _baixar_via_ftp_direto(uf: str, ano: int, mes: int) -> ResultadoDownload | None:
    """Baixa o arquivo .dbc do grupo RD direto do FTP oficial do DATASUS,
    sem depender do catálogo do pysus (ver nota no topo do módulo).

    Devolve `None` quando a listagem AO VIVO do diretório confirma que o
    arquivo não existe (competência genuinamente sem dado publicado).
    Levanta exceção em caso de falha de rede/FTP/decodificação — o
    chamador decide o que fazer (registrar como erro comum, tentar de
    novo, etc.)."""
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
        except Exception:  # noqa: BLE001
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
    """Baixa uma competência do grupo RD (AIH Reduzida) do SIH/SUS.

    Tenta primeiro a API moderna do pysus e, se vier vazia ou falhar,
    recorre ao FTP oficial direto (bypass total do catálogo do pysus —
    ver nota no topo do módulo). Levanta `RuntimeError` apenas se ambas
    as tentativas falharem com exceção; se ambas devolverem vazio sem
    erro (incluindo a listagem ao vivo do FTP confirmando ausência do
    arquivo), retorna um resultado com `total_bruto=0`.
    """
    erros: list[str] = []

    try:
        import pysus as pysus_mod  # type: ignore

        df = pysus_mod.ftp.sih(state=uf, year=ano, month=mes, group="RD", as_dataframe=True)
        df = _dataframe_de_retorno_pysus(df)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return ResultadoDownload(bruto=df, total_bruto=len(df))
    except Exception as exc:  # noqa: BLE001
        erros.append(f"pysus.ftp.sih: {exc}")

    try:
        resultado_ftp = _baixar_via_ftp_direto(uf, ano, mes)
        if resultado_ftp is not None:
            return resultado_ftp
    except Exception as exc:  # noqa: BLE001
        erros.append(f"ftp direto (bypass catálogo pysus): {exc}")

    if erros:
        raise RuntimeError(
            "Não foi possível baixar via pysus. Detalhes: " + " | ".join(erros)
        )
    return ResultadoDownload(bruto=pd.DataFrame(), total_bruto=0)
