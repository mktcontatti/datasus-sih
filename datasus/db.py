# -*- coding: utf-8 -*-
"""Camada de acesso ao banco (SQLite).

Todo o estado do projeto (catálogo de procedimentos, status de coleta
por competência, procedimentos coletados, e os caches de nomes de
estabelecimento/município) vive num único arquivo SQLite
(`data/sih.db`). O modo WAL garante que leituras e escritas concorrentes
sejam seguras sem nenhum mecanismo de trava adicional.

Dado bruto e dado enriquecido (nomes de estabelecimento/município)
ficam sempre em tabelas separadas: o enriquecimento é feito por JOIN na
hora da consulta (ver `datasus/consultas.py`), nunca gravado junto com
o dado coletado.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from datasus import settings

SCHEMA = """
-- Procedimentos SIGTAP monitorados (carregados de data/procedimentos.xlsx).
CREATE TABLE IF NOT EXISTS procedimentos (
    codigo_sigtap   TEXT PRIMARY KEY,
    descricao       TEXT,
    grupo           TEXT,
    subgrupo        TEXT,
    categoria       TEXT,
    tipo            TEXT,       -- 'CC' (cirurgia cardiaca) ou 'Transplante'
    ativo           INTEGER NOT NULL DEFAULT 1
);

-- Status de coleta por competência (UF + ano/mês de processamento).
CREATE TABLE IF NOT EXISTS competencias (
    uf              TEXT NOT NULL,
    ano             INTEGER NOT NULL,
    mes             INTEGER NOT NULL,
    status          TEXT NOT NULL,
        -- 'sucesso'                  : baixou e filtrou normalmente (pode ter
        --                              zero linhas filtradas, se não houve
        --                              nenhum procedimento monitorado).
        -- 'suspeita_falha_silenciosa': o download bruto voltou vazio (0 AIH),
        --                              o que é muito improvável para uma UF
        --                              inteira num mês inteiro — entra na
        --                              fila de nova tentativa automaticamente.
        -- 'falha'                    : todas as tentativas geraram exceção.
    total_bruto     INTEGER,        -- registros no arquivo baixado, antes do filtro
    total_filtrado  INTEGER,        -- registros após filtrar pelos códigos monitorados
    tentativas      INTEGER NOT NULL DEFAULT 0,
    erro            TEXT,
    atualizado_em   TEXT NOT NULL,
    PRIMARY KEY (uf, ano, mes)
);

-- Procedimentos efetivamente coletados (dado bruto/organizado — sem
-- nenhum nome de estabelecimento ou município embutido).
CREATE TABLE IF NOT EXISTS procedimentos_realizados (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uf                  TEXT NOT NULL,
    ano                 INTEGER NOT NULL,   -- ano de competência (processamento)
    mes                 INTEGER NOT NULL,   -- mês de competência (processamento)
    n_aih               TEXT,
    cnes                TEXT,
    codigo_sigtap       TEXT NOT NULL,
    municipio_codigo    TEXT
);
CREATE INDEX IF NOT EXISTS idx_proc_uf_ano_mes
    ON procedimentos_realizados (uf, ano, mes);
CREATE INDEX IF NOT EXISTS idx_proc_cnes
    ON procedimentos_realizados (cnes);
CREATE INDEX IF NOT EXISTS idx_proc_sigtap
    ON procedimentos_realizados (codigo_sigtap);
CREATE UNIQUE INDEX IF NOT EXISTS idx_proc_dedup_aih
    ON procedimentos_realizados (uf, ano, mes, n_aih, codigo_sigtap)
    WHERE n_aih IS NOT NULL AND n_aih <> '';

-- Cache de nomes de estabelecimentos (API pública do CNES).
CREATE TABLE IF NOT EXISTS estabelecimentos (
    cnes            TEXT PRIMARY KEY,
    razao_social    TEXT,
    nome_fantasia   TEXT,
    atualizado_em   TEXT NOT NULL
);

-- Cache de municípios (IBGE): nome e região a partir do código IBGE.
CREATE TABLE IF NOT EXISTS municipios (
    codigo_ibge     TEXT PRIMARY KEY,
    nome            TEXT,
    uf              TEXT,
    regiao          TEXT
);
-- Auditoria automática de qualidade, sem alterar o dado coletado.
CREATE TABLE IF NOT EXISTS auditoria_qualidade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT NOT NULL,
    chave           TEXT,
    detalhe         TEXT,
    detectado_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auditoria_tipo ON auditoria_qualidade (tipo);
"""


def conectar() -> sqlite3.Connection:
    """Abre uma conexão com o banco (modo WAL) e garante que o schema
    exista."""
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def conexao():
    """Context manager para leitura (ou leituras avulsas): garante que a
    conexão é fechada ao final. Para escritas, use `transacao()`."""
    conn = conectar()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transacao():
    """Context manager que abre uma conexão, garante COMMIT no final (ou
    ROLLBACK se der erro) e fecha a conexão."""
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar_banco(caminho: Path | None = None) -> None:
    """Cria o arquivo do banco e todas as tabelas, se ainda não existirem.
    Seguro para chamar várias vezes (idempotente)."""
    if caminho is not None:
        settings.DB_PATH = caminho  # usado em testes
    with transacao() as conn:
        conn.executescript(SCHEMA)
