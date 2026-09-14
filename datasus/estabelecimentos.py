# -*- coding: utf-8 -*-
"""Enriquecimento confiável de Razão Social e Nome Fantasia por CNES.

Estratégia: consulta direta pelo código CNES; se a API não aceitar ou não
retornar o registro, usa a listagem do município somente como fallback.
O cache existente só é substituído quando um novo nome válido é encontrado.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
import requests

from datasus.codigos import normalizar_codigo
from datasus.db import conexao, transacao

API_BASE = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
TIMEOUT = 60
PAUSA_ENTRE_CONSULTAS = 0.12
TAMANHO_PAGINA = 100

def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _itens(dados) -> list[dict]:
    if isinstance(dados, dict):
        for chave in ("estabelecimentos", "items", "results"):
            if isinstance(dados.get(chave), list):
                dados = dados[chave]
                break
        else:
            dados = [dados] if dados.get("codigo_cnes") else []
    return [x for x in dados if isinstance(x, dict)] if isinstance(dados, list) else []

def _extrair(item: dict) -> tuple[str | None, str | None, str | None]:
    codigo = normalizar_codigo(item.get("codigo_cnes"), 7)
    razao = str(item.get("nome_razao_social") or "").strip() or None
    fantasia = str(item.get("nome_fantasia") or "").strip() or None
    return codigo, razao, fantasia

def _buscar_direto(cnes: str) -> tuple[str | None, str | None] | None:
    """Busca por CNES exato usando o endpoint de recurso único
    (`/cnes/estabelecimentos/{codigo_cnes}`).

    O endpoint de listagem (`/cnes/estabelecimentos?codigo_cnes=...`)
    ignora silenciosamente o parâmetro `codigo_cnes` e sempre devolve a
    primeira página padrão — por isso a busca exata precisa ser feita
    pelo endpoint de recurso único, que devolve 404 quando o CNES não
    existe.
    """
    resposta = requests.get(f"{API_BASE}/{cnes}", timeout=TIMEOUT)
    if resposta.status_code == 404:
        return None
    resposta.raise_for_status()
    codigo, razao, fantasia = _extrair(resposta.json())
    if codigo == cnes and (razao or fantasia):
        return razao, fantasia
    return None

def _buscar_por_municipio(codigo_municipio: str) -> dict[str, tuple[str | None, str | None]]:
    encontrados = {}
    offset = 0
    while True:
        resposta = requests.get(API_BASE, params={"codigo_municipio": int(codigo_municipio), "limit": TAMANHO_PAGINA, "offset": offset}, timeout=TIMEOUT)
        resposta.raise_for_status()
        itens = _itens(resposta.json())
        if not itens:
            break
        for item in itens:
            codigo, razao, fantasia = _extrair(item)
            if codigo and (razao or fantasia):
                encontrados[codigo] = (razao, fantasia)
        if len(itens) < TAMANHO_PAGINA:
            break
        offset += TAMANHO_PAGINA
    return encontrados

def _todos_cnes() -> list[str]:
    with conexao() as conn:
        rows = conn.execute("SELECT DISTINCT cnes FROM procedimentos_realizados WHERE cnes IS NOT NULL AND cnes<>''").fetchall()
    return sorted(r["cnes"] for r in rows)

def codigos_sem_nome() -> list[str]:
    with conexao() as conn:
        rows = conn.execute("""SELECT DISTINCT pr.cnes FROM procedimentos_realizados pr
            LEFT JOIN estabelecimentos e ON e.cnes=pr.cnes
            WHERE pr.cnes IS NOT NULL AND pr.cnes<>''
              AND (e.cnes IS NULL OR (e.razao_social IS NULL AND e.nome_fantasia IS NULL))""").fetchall()
    return sorted(r["cnes"] for r in rows)

def _municipios_por_cnes(codigos: list[str]) -> dict[str, str]:
    mapa = {}
    with conexao() as conn:
        for inicio in range(0, len(codigos), 500):
            lote = codigos[inicio:inicio + 500]
            marcadores = ",".join("?" for _ in lote)
            if not marcadores:
                continue
            rows = conn.execute(f"""SELECT cnes, municipio_codigo, COUNT(*) AS n
                FROM procedimentos_realizados WHERE cnes IN ({marcadores})
                  AND municipio_codigo IS NOT NULL AND municipio_codigo<>''
                GROUP BY cnes, municipio_codigo ORDER BY cnes, n DESC""", lote).fetchall()
            for row in rows:
                mapa.setdefault(row["cnes"], row["municipio_codigo"])
    return mapa

def atualizar_cache(forcar: bool = False) -> int:
    pendentes = _todos_cnes() if forcar else codigos_sem_nome()
    if not pendentes:
        print("[estabelecimentos] Todos os nomes já estão no cache.")
        return 0

    municipios = _municipios_por_cnes(pendentes)
    fallback_cache: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    gravar = []
    falhas = []

    for indice, cnes in enumerate(pendentes, 1):
        dados = None
        try:
            dados = _buscar_direto(cnes)
        except Exception as exc:  # fallback abaixo
            erro_direto = f"{type(exc).__name__}: {exc}"
        else:
            erro_direto = "sem resultado"

        if not dados:
            municipio = municipios.get(cnes)
            if municipio:
                try:
                    if municipio not in fallback_cache:
                        fallback_cache[municipio] = _buscar_por_municipio(municipio)
                    dados = fallback_cache[municipio].get(cnes)
                except Exception as exc:
                    erro_direto += f"; fallback {type(exc).__name__}: {exc}"

        if dados and any(dados):
            gravar.append((cnes, dados[0], dados[1], _agora()))
        else:
            falhas.append(("cnes_sem_nome", cnes, erro_direto, _agora()))

        if indice % 100 == 0:
            print(f"[estabelecimentos] {indice}/{len(pendentes)} consultados; {len(gravar)} válidos.")
        time.sleep(PAUSA_ENTRE_CONSULTAS)

    with transacao() as conn:
        if gravar:
            conn.executemany("""INSERT INTO estabelecimentos (cnes,razao_social,nome_fantasia,atualizado_em)
                VALUES (?,?,?,?) ON CONFLICT(cnes) DO UPDATE SET
                razao_social=excluded.razao_social, nome_fantasia=excluded.nome_fantasia,
                atualizado_em=excluded.atualizado_em""", gravar)
        conn.execute("DELETE FROM auditoria_qualidade WHERE tipo='cnes_sem_nome'")
        if falhas:
            conn.executemany("INSERT INTO auditoria_qualidade (tipo,chave,detalhe,detectado_em) VALUES (?,?,?,?)", falhas)

    print(f"[estabelecimentos] Concluído: {len(gravar)}/{len(pendentes)} nomes válidos; {len(falhas)} pendências auditadas.")
    return len(gravar)
