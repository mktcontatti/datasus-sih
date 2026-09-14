#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interface de linha de comando única do DATASUS SIH.

Uso:
    python cli.py importar-procedimentos
    python cli.py coletar [--ufs UF ...] [--anos ANO ...] [--meses "1-12"]
                          [--forcar] [--paralelo N]
    python cli.py retentar-falhas
    python cli.py atualizar-municipios
    python cli.py corrigir-nomes [--forcar]
    python cli.py cobertura
    python cli.py integridade
    python cli.py resetar --confirmar
"""
from __future__ import annotations

import argparse
import sys

from datasus import catalogo, consultas, coleta, estabelecimentos, municipios, settings
from datasus.coleta import parse_meses
from datasus.db import inicializar_banco


def cmd_importar_procedimentos(args):
    catalogo.importar_xlsx()


def cmd_coletar(args):
    coleta.rodar_coleta(
        ufs=args.ufs,
        anos=args.anos,
        meses=parse_meses(args.meses) if args.meses else None,
        forcar=args.forcar,
        paralelo=args.paralelo,
    )


def cmd_retentar_falhas(args):
    coleta.retentar_falhas(paralelo=args.paralelo)


def cmd_atualizar_municipios(args):
    municipios.atualizar_cache()


def cmd_corrigir_nomes(args):
    estabelecimentos.atualizar_cache(forcar=args.forcar)


def cmd_cobertura(args):
    ano_base = settings.ano_base_atual()
    r = consultas.relatorio_cobertura(ano_base)
    print("=" * 64)
    print(" COBERTURA — DADOS SIH/SUS")
    print("=" * 64)
    print(f" Ano-base: {r['ano_base']}")
    print(f" {r['concluido']}/{r['esperado']} competências ({r['percentual']:.0%})")
    if r["faltantes"]:
        print(f" Faltando {len(r['faltantes'])} competência(s):")
        por_uf: dict[str, list[int]] = {}
        for uf, mes in r["faltantes"]:
            por_uf.setdefault(uf, []).append(mes)
        for uf in sorted(por_uf):
            print(f"   - {uf}: {', '.join(f'{m:02d}' for m in sorted(por_uf[uf]))}")
    else:
        print(f" {r['ano_base']} COMPLETO.")
    if r["suspeitas_falha_silenciosa"]:
        print(f" ⚠ {len(r['suspeitas_falha_silenciosa'])} competência(s) com suspeita de "
              f"falha silenciosa (serão reprocessadas na próxima coleta).")
    if r["falhas"]:
        print(f" ✗ {len(r['falhas'])} competência(s) com falha registrada "
              f"(rode `python cli.py retentar-falhas`).")
    print("=" * 64)


def cmd_integridade(args):
    print("=" * 64)
    print(" INTEGRIDADE — controle x dados reais")
    print("=" * 64)
    divergentes = consultas.relatorio_integridade()
    if divergentes.empty:
        print(" Nenhuma divergência encontrada. Os dados estão consistentes.")
    else:
        print(f" {len(divergentes)} competência(s) divergente(s):")
        print(divergentes.to_string(index=False))
    print("=" * 64)



def cmd_diagnostico(args):
    r = consultas.relatorio_diagnostico()
    print("=" * 64)
    print(" DIAGNÓSTICO DE QUALIDADE")
    print("=" * 64)
    for chave, valor in r.items():
        print(f" {chave.replace('_', ' ').capitalize()}: {valor}")
    print("=" * 64)

def cmd_resetar(args):
    if not args.confirmar:
        print("Isso apaga TODOS os dados coletados (não o catálogo de "
              "procedimentos). Rode de novo com --confirmar para prosseguir.")
        return
    from datasus.db import transacao
    with transacao() as conn:
        conn.execute("DELETE FROM procedimentos_realizados")
        conn.execute("DELETE FROM competencias")
    print("[resetar] Dados coletados apagados. O catálogo de procedimentos "
          "e os caches de nomes foram mantidos.")


def main():
    inicializar_banco()

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("importar-procedimentos").set_defaults(func=cmd_importar_procedimentos)

    p_coletar = sub.add_parser("coletar")
    p_coletar.add_argument("--ufs", nargs="+", default=None)
    p_coletar.add_argument("--anos", nargs="+", type=int, default=None)
    p_coletar.add_argument("--meses", type=str, default=None, help='ex.: "1-12" ou "1,3,5"')
    p_coletar.add_argument("--forcar", action="store_true")
    p_coletar.add_argument("--paralelo", type=int, default=None)
    p_coletar.set_defaults(func=cmd_coletar)

    p_retentar = sub.add_parser("retentar-falhas")
    p_retentar.add_argument("--paralelo", type=int, default=None)
    p_retentar.set_defaults(func=cmd_retentar_falhas)

    sub.add_parser("atualizar-municipios").set_defaults(func=cmd_atualizar_municipios)

    p_nomes = sub.add_parser("corrigir-nomes")
    p_nomes.add_argument("--forcar", action="store_true")
    p_nomes.set_defaults(func=cmd_corrigir_nomes)

    sub.add_parser("cobertura").set_defaults(func=cmd_cobertura)
    sub.add_parser("integridade").set_defaults(func=cmd_integridade)
    sub.add_parser("diagnostico").set_defaults(func=cmd_diagnostico)

    p_resetar = sub.add_parser("resetar")
    p_resetar.add_argument("--confirmar", action="store_true")
    p_resetar.set_defaults(func=cmd_resetar)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
