import pandas as pd

from datasus.exportar import adicionar_linha_total, gerar_excel, gerar_pdf

def test_gerar_excel_com_tabela_vazia():
    df = pd.DataFrame(columns=["Razao Social", "Procedimentos"])
    conteudo = gerar_excel(df, "Estabelecimentos")
    assert len(conteudo) > 0

def test_gerar_pdf_com_tabela_vazia():
    df = pd.DataFrame(columns=["Razao Social", "Procedimentos"])
    conteudo = gerar_pdf(df, "Estabelecimentos")
    assert len(conteudo) > 0

def test_adicionar_linha_total_com_tabela_vazia():
    df = pd.DataFrame(columns=["Razao Social", "Procedimentos"])
    resultado = adicionar_linha_total(df, "Procedimentos")
    assert resultado.empty
