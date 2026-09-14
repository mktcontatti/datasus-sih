# -*- coding: utf-8 -*-
"""Configurações centrais do projeto: caminhos, ano-base e aparência.

Este é o único lugar do projeto com caminhos de arquivo fixos — todo o
resto do código importa daqui.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "sih.db"
PROCEDIMENTOS_XLSX = DATA_DIR / "procedimentos.xlsx"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Estados e agrupamento por região
# ---------------------------------------------------------------------------
REGIAO_POR_UF = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}
TODAS_UFS = sorted(REGIAO_POR_UF.keys())

# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
GRUPO_SIH = "RD"                 # grupo "AIH Reduzida" do SIH/SUS
MAX_DOWNLOADS_PARALELOS = 2
MAX_TENTATIVAS_POR_COMPETENCIA = 3
PAUSA_ENTRE_TENTATIVAS_SEG = 5

# ---------------------------------------------------------------------------
# Ano-base: o app consolida um ano por vez, usando o ano/mês de
# COMPETÊNCIA (processamento/faturamento da AIH) — a mesma dimensão de
# tempo usada por padrão no TabNet do DATASUS.
#
# O DATASUS publica os arquivos de competência com um atraso
# administrativo (tipicamente 1-2 meses). Por isso, o ano-base
# considerado "fechado" só avança para o ano corrente a partir de
# MES_VIRADA, dando tempo para a competência de dezembro do ano
# anterior ser publicada.
# ---------------------------------------------------------------------------
MES_VIRADA = 2          # a partir deste mês do ano, o ano-base avança
ANO_BASE_FIXO: int | None = None  # None = automático; ou fixe um ano, ex.: 2025


def ano_base_atual(hoje: date | None = None) -> int:
    """Ano de competência que deve ser consolidado agora."""
    if ANO_BASE_FIXO is not None:
        return int(ANO_BASE_FIXO)
    hoje = hoje or date.today()
    return hoje.year - 2 if hoje.month < MES_VIRADA else hoje.year - 1


# ---------------------------------------------------------------------------
# Aparência do painel (paleta neutra, inspirada nas Apple HIG)
# ---------------------------------------------------------------------------
COR_FUNDO = "#F5F5F7"
COR_CARD = "#FFFFFF"
COR_TEXTO = "#1D1D1F"
COR_TEXTO_SECUNDARIO = "#6E6E73"
COR_BORDA = "#D2D2D7"
COR_ACENTO = "#0B3D66"
COR_ACENTO_ESCURO = "#082A47"
COR_SUCESSO = "#34C759"
COR_ALERTA = "#FF9F0A"

PALETA_CATEGORIAS = [
    "#0B3D66", "#6E6E73", "#3D6B94", "#8E8E93",
    "#164C7E", "#4A7FA5", "#98989D", "#082A47",
]

MESES_NOME_CURTO = [
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]
MESES_NOME_LONGO = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
