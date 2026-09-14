# -*- coding: utf-8 -*-
"""Cache de municípios (nome, UF, região) a partir da API pública do
IBGE.

A API do IBGE devolve a hierarquia administrativa em um de dois
formatos possíveis, dependendo do município — este módulo tenta ambos
e ignora individualmente qualquer registro que não se encaixe em
nenhum dos dois, sem interromper a atualização do restante do cache.

O código de município usado no SIH/SUS (campo MUNIC_MOV/MUNIC_RES) tem
6 dígitos, enquanto a API do IBGE devolve códigos de 7 dígitos (6 +
dígito verificador) — por isso truncamos para 6 dígitos ao gravar o
cache.
"""
from __future__ import annotations

import requests

from datasus.db import transacao

API_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
TIMEOUT = 60


def _extrair_uf_regiao(municipio: dict) -> tuple[str | None, str | None]:
    """Tenta os dois formatos conhecidos de resposta da API do IBGE.
    Devolve (uf, regiao) ou (None, None) se nenhum formato funcionar."""
    try:
        uf_info = municipio["microrregiao"]["mesorregiao"]["UF"]
        return uf_info.get("sigla"), (uf_info.get("regiao") or {}).get("nome")
    except (KeyError, TypeError, AttributeError):
        pass

    try:
        uf_info = municipio["regiao-imediata"]["regiao-intermediaria"]["UF"]
        return uf_info.get("sigla"), (uf_info.get("regiao") or {}).get("nome")
    except (KeyError, TypeError, AttributeError):
        pass

    return None, None


def atualizar_cache() -> int:
    """Baixa a lista completa de municípios do IBGE e grava no cache
    local. Devolve quantos municípios foram gravados com sucesso."""
    resp = requests.get(API_MUNICIPIOS, timeout=TIMEOUT)
    resp.raise_for_status()
    municipios = resp.json()

    linhas = []
    pulados = 0
    for m in municipios:
        try:
            codigo_7 = str(m.get("id", "")).strip()
            if not codigo_7:
                pulados += 1
                continue
            codigo_6 = codigo_7[:6]
            nome = m.get("nome")
            uf, regiao = _extrair_uf_regiao(m)
            linhas.append((codigo_6, nome, uf, regiao))
        except Exception:  # noqa: BLE001
            pulados += 1
            continue

    if not linhas:
        print("[municipios] AVISO: nenhum município processado com sucesso.")
        return 0

    with transacao() as conn:
        conn.executemany(
            "INSERT INTO municipios (codigo_ibge, nome, uf, regiao) VALUES (?,?,?,?) "
            "ON CONFLICT(codigo_ibge) DO UPDATE SET "
            "  nome=excluded.nome, uf=excluded.uf, regiao=excluded.regiao",
            linhas,
        )

    msg = f"[municipios] {len(linhas)} município(s) atualizado(s) no cache."
    if pulados:
        msg += f" ({pulados} registro(s) pulado(s).)"
    print(msg)
    return len(linhas)
