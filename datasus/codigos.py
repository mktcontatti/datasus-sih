# -*- coding: utf-8 -*-
"""Funções puras de normalização de códigos (CNES, SIGTAP, IBGE, etc.).

Deliberadamente sem nenhuma dependência de pandas/sqlite/rede: são as
funções mais fáceis de testar do projeto, e as que mais precisam estar
certas (qualquer erro aqui se propaga silenciosamente para o dataset
inteiro). Ver tests/test_codigos.py.
"""
from __future__ import annotations


def normalizar_codigo(valor, digitos: int = 7) -> str | None:
    """Normaliza um código (CNES, SIGTAP, IBGE...) para string com zeros
    à esquerda. Trata o caso comum de o valor chegar como float
    (ex.: 2001586.0) por causa de colunas do pandas com nulos misturados.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto == "" or texto.lower() == "nan":
        return None
    if texto.endswith(".0"):
        texto = texto[:-2]
    elif "." in texto:
        texto = texto.split(".")[0]
    texto = "".join(ch for ch in texto if ch.isdigit())
    if not texto:
        return None
    return texto.zfill(digitos)
