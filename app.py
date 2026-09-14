# -*- coding: utf-8 -*-
"""Painel SIH/SUS - DATASUS.

Rodar com:
    streamlit run app.py
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from datasus import consultas, settings
from datasus.db import inicializar_banco
from datasus.exportar import adicionar_linha_total, gerar_excel, gerar_pdf

# ---------------------------------------------------------------------------
# Fuso horário do painel (Brasil, horário de São Paulo)
# ---------------------------------------------------------------------------
FUSO_BR = ZoneInfo("America/Sao_Paulo")

# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------
inicializar_banco()

st.set_page_config(
    page_title="SIH/SUS · DATASUS",
    layout="wide",
    page_icon="🩺",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        width: 100%;
        max-width: 100%;
    }
    [data-testid="stMainBlockContainer"] {
        width: 100%;
        max-width: 100%;
        padding-top: 5.5rem;
        padding-left: 2rem;
        padding-right: 2rem;
        padding-bottom: 3rem;
    }
    [data-testid="stHeader"] {
        background: transparent;
    }
    [data-testid="stDataFrame"] {
        width: 100%;
        max-width: 100%;
        overflow-x: auto !important;
    }
    [data-testid="stDataFrame"] > div {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
    .bloco-titulo {
        font-size: 1.6rem;
        font-weight: 700;
        color: #1D1D1F;
        margin: 0 0 .2rem 0;
        line-height: 1.3;
        overflow: visible;
        white-space: normal;
    }
    .bloco-sub {
        font-size: .85rem;
        color: #6E6E73;
        margin: 0 0 .6rem 0;
    }
    .secao {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1D1D1F;
        margin: 1.2rem 0 .4rem 0;
    }
    .rotulo {
        font-size: .8rem;
        font-weight: 600;
        color: #6E6E73;
        margin: .45rem 0 .1rem 0;
    }
    .linha-fina {
        border: 0;
        border-top: 1px solid #D2D2D7;
        margin: .9rem 0 1.1rem 0;
    }
    div[data-testid="stButton"] button {
        min-height: 2rem;
        font-size: .8rem;
        color: #6E6E73;
        border-color: #D2D2D7;
        background: transparent;
    }
    @media (max-width: 900px) {
        [data-testid="stMainBlockContainer"] {
            padding-top: 5.5rem;
            padding-left: 1rem;
            padding-right: 1rem;
            padding-bottom: 2rem;
        }
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        [data-testid="column"] {
            min-width: 240px;
            flex: 1 1 240px;
        }
    }
    @media (max-width: 600px) {
        [data-testid="stMainBlockContainer"] {
            padding-top: 5.5rem;
            padding-left: .65rem;
            padding-right: .65rem;
            padding-bottom: 1.5rem;
        }
        [data-testid="column"] {
            min-width: 100%;
            width: 100%;
            flex: 1 1 100%;
        }
        .bloco-titulo {
            font-size: 1.25rem;
        }
        .bloco-sub {
            line-height: 1.4;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Carregamento dos dados
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner="Carregando dados...")
def carregar_dataset(ano: int) -> pd.DataFrame:
    return consultas.dataset_ano(ano)


@st.cache_data(ttl=300)
def carregar_cobertura(ano_base: int) -> dict:
    return consultas.relatorio_cobertura(ano_base)


@st.cache_data(ttl=300)
def carregar_ultima_competencia(ano_base: int) -> tuple[int, int] | None:
    return consultas.ultima_competencia_coletada(ano_base)


ano_base = settings.ano_base_atual()
df = carregar_dataset(ano_base)
cobertura = carregar_cobertura(ano_base)
ultima_comp = carregar_ultima_competencia(ano_base)

# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="bloco-titulo">Procedimentos SUS por Estabelecimento</div>',
    unsafe_allow_html=True,
)

if ultima_comp:
    _, mes_ult = ultima_comp
    texto_cobertura = f"Dados até {settings.MESES_NOME_LONGO[mes_ult - 1]} de {ano_base}"
else:
    texto_cobertura = "Nenhum dado coletado ainda"

st.markdown(
    f'<div class="bloco-sub">Atualizado em {datetime.now(FUSO_BR).strftime("%d/%m/%Y às %H:%M")} · '
    f'SIH/SUS · DATASUS · Cirurgias cardíacas e transplantes · {texto_cobertura}</div>',
    unsafe_allow_html=True,
)

if cobertura["faltantes"] and ultima_comp:
    st.caption(
        f"{len(cobertura['faltantes'])} competência(s) ainda pendente(s) de coleta em {ano_base}."
    )

if df.empty:
    st.info("Nenhum dado coletado ainda para o ano-base atual.")
    st.stop()

# ---------------------------------------------------------------------------
# Preparação das opções dos filtros
# ---------------------------------------------------------------------------
regioes_disponiveis = sorted(df["regiao"].dropna().astype(str).unique().tolist())
ufs_disponiveis = sorted(df["uf"].dropna().astype(str).unique().tolist())
categorias_disponiveis = sorted(df["categoria"].dropna().astype(str).unique().tolist())

regiao_para_ufs = {
    regiao: sorted(
        df.loc[df["regiao"] == regiao, "uf"].dropna().astype(str).unique().tolist()
    )
    for regiao in regioes_disponiveis
}

tipo_para_categorias = {
    "Cirurgia Cardíaca": sorted(
        df.loc[df["tipo"] == "Cirurgia", "categoria"].dropna().astype(str).unique().tolist()
    ),
    "Transplantes": sorted(
        df.loc[df["tipo"] == "Transplante", "categoria"].dropna().astype(str).unique().tolist()
    ),
}

# ---------------------------------------------------------------------------
# Estado inicial dos filtros
# ---------------------------------------------------------------------------
VALORES_INICIAIS = {
    "filtro_tipo": "Todos",
    "filtro_regiao": "Todos",
    "filtro_uf": ["Todos"],
    "filtro_categoria": ["Todos"],
    "anterior_uf": ["Todos"],
    "anterior_categoria": ["Todos"],
}
for chave, valor in VALORES_INICIAIS.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor


# ---------------------------------------------------------------------------
# Funções de sincronização dos filtros
# ---------------------------------------------------------------------------
def sincronizar_tipo() -> None:
    """Sincroniza as categorias quando o tipo é alterado."""
    tipo = st.session_state.get("filtro_tipo", "Todos")
    if tipo == "Todos":
        st.session_state["filtro_categoria"] = ["Todos"]
    else:
        categorias = tipo_para_categorias.get(tipo, [])
        st.session_state["filtro_categoria"] = categorias or ["Todos"]
    st.session_state["anterior_categoria"] = list(st.session_state["filtro_categoria"])


def sincronizar_regiao() -> None:
    """Sincroniza as UFs quando a região é alterada."""
    regiao = st.session_state.get("filtro_regiao", "Todos")
    if regiao == "Todos":
        st.session_state["filtro_uf"] = ["Todos"]
    else:
        st.session_state["filtro_uf"] = regiao_para_ufs.get(regiao, []) or ["Todos"]
    st.session_state["anterior_uf"] = list(st.session_state["filtro_uf"])


def normalizar_multifiltro(chave: str, chave_anterior: str) -> None:
    """Mantém 'Todos' exclusivo em filtros de múltipla seleção."""
    atual = list(st.session_state.get(chave, []))
    anterior = list(st.session_state.get(chave_anterior, ["Todos"]))
    if not atual:
        atual = ["Todos"]
    elif "Todos" in atual and len(atual) > 1:
        if "Todos" in anterior:
            atual = [item for item in atual if item != "Todos"]
        else:
            atual = ["Todos"]
    st.session_state[chave] = atual
    st.session_state[chave_anterior] = list(atual)


def normalizar_uf() -> None:
    normalizar_multifiltro("filtro_uf", "anterior_uf")


def normalizar_categoria() -> None:
    normalizar_multifiltro("filtro_categoria", "anterior_categoria")


def limpar_filtros() -> None:
    """Retorna todos os filtros ao estado inicial."""
    for chave, valor in VALORES_INICIAIS.items():
        st.session_state[chave] = valor.copy() if isinstance(valor, list) else valor


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
col_filtros, col_limpar = st.columns([5, 1], vertical_alignment="bottom")
with col_filtros:
    st.markdown('<div class="secao">Filtros</div>', unsafe_allow_html=True)
with col_limpar:
    st.button(
        "Limpar filtros",
        on_click=limpar_filtros,
        use_container_width=True,
    )

# Dupla 1: Tipo de procedimento + Categoria
col_tipo, col_categoria = st.columns([1, 3], gap="small")
with col_tipo:
    st.markdown('<div class="rotulo">Tipo de procedimento</div>', unsafe_allow_html=True)
    st.pills(
        "Tipo de procedimento",
        ["Todos", "Cirurgia Cardíaca", "Transplantes"],
        key="filtro_tipo",
        on_change=sincronizar_tipo,
        label_visibility="collapsed",
    )
with col_categoria:
    st.markdown('<div class="rotulo">Categoria</div>', unsafe_allow_html=True)
    st.pills(
        "Categoria",
        ["Todos"] + categorias_disponiveis,
        key="filtro_categoria",
        selection_mode="multi",
        on_change=normalizar_categoria,
        label_visibility="collapsed",
    )

# Dupla 2: Região + Estado (UF)
col_regiao, col_uf = st.columns([1, 3], gap="small")
with col_regiao:
    st.markdown('<div class="rotulo">Região</div>', unsafe_allow_html=True)
    st.pills(
        "Região",
        ["Todos"] + regioes_disponiveis,
        key="filtro_regiao",
        on_change=sincronizar_regiao,
        label_visibility="collapsed",
    )
with col_uf:
    st.markdown('<div class="rotulo">Estado</div>', unsafe_allow_html=True)
    st.pills(
        "Estado",
        ["Todos"] + ufs_disponiveis,
        key="filtro_uf",
        selection_mode="multi",
        on_change=normalizar_uf,
        label_visibility="collapsed",
    )

# ---------------------------------------------------------------------------
# Valores efetivos dos filtros
# ---------------------------------------------------------------------------
tipo_sel = st.session_state["filtro_tipo"]
regiao_sel = st.session_state["filtro_regiao"]
uf_sel = st.session_state["filtro_uf"]
categoria_sel = st.session_state["filtro_categoria"]

# ---------------------------------------------------------------------------
# Aplicação dos filtros
# ---------------------------------------------------------------------------
df_f = df.copy()
if tipo_sel == "Cirurgia Cardíaca":
    df_f = df_f[df_f["tipo"] == "Cirurgia"]
elif tipo_sel == "Transplantes":
    df_f = df_f[df_f["tipo"] == "Transplante"]
if regiao_sel != "Todos":
    df_f = df_f[df_f["regiao"] == regiao_sel]
if "Todos" not in uf_sel:
    df_f = df_f[df_f["uf"].isin(uf_sel)]
if "Todos" not in categoria_sel:
    df_f = df_f[df_f["categoria"].isin(categoria_sel)]

filtros_aplicados = {
    "Tipo": "" if tipo_sel == "Todos" else tipo_sel,
    "Região": "" if regiao_sel == "Todos" else regiao_sel,
    "UF": "" if "Todos" in uf_sel else ", ".join(uf_sel),
    "Categoria": "" if "Todos" in categoria_sel else ", ".join(categoria_sel),
}

st.markdown('<hr class="linha-fina">', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3)
c1.metric("Procedimentos", f"{len(df_f):,}".replace(",", "."))
c2.metric("Estabelecimentos", df_f["cnes"].nunique())
c3.metric("UFs atendidas", df_f["uf"].nunique())

st.markdown('<div class="secao">Estabelecimentos</div>', unsafe_allow_html=True)
termo_busca = st.text_input(
    "Buscar por nome (Razão Social ou Nome Fantasia)",
    placeholder="ex.: Hospital das Clínicas",
)
col_ordenar, col_ordem = st.columns(2)
with col_ordenar:
    ordenar_por = st.selectbox(
        "Ordenar por", ["Procedimentos", "Razão Social", "Nome Fantasia"]
    )
with col_ordem:
    ordem = st.selectbox("Ordem", ["Maior primeiro", "Menor primeiro"])

agg = (
    df_f.groupby("cnes")
    .agg(
        Razao_Social=("razao_social", "first"),
        Nome_Fantasia=("nome_fantasia", "first"),
        Municipio=("municipio_nome", "first"),
        UF=("uf", "first"),
        Regiao=("regiao", "first"),
        Procedimentos=("cnes", "count"),
    )
    .reset_index(drop=True)
)
agg = agg.rename(
    columns={
        "Razao_Social": "Razão Social",
        "Nome_Fantasia": "Nome Fantasia",
        "Municipio": "Município",
        "Regiao": "Região",
    }
)

if termo_busca:
    termo = termo_busca.strip().lower()
    agg = agg[
        agg["Razão Social"].astype(str).str.lower().str.contains(termo, na=False)
        | agg["Nome Fantasia"].astype(str).str.lower().str.contains(termo, na=False)
    ]

coluna_ordenacao = {
    "Procedimentos": "Procedimentos",
    "Razão Social": "Razão Social",
    "Nome Fantasia": "Nome Fantasia",
}[ordenar_por]
agg = agg.sort_values(
    coluna_ordenacao,
    ascending=(ordem == "Menor primeiro"),
)

st.caption(f"{len(agg)} estabelecimento(s) no recorte atual.")

tabela_com_total = adicionar_linha_total(agg, "Procedimentos")
st.dataframe(
    tabela_com_total,
    use_container_width=True,
    hide_index=True,
    height=520,
    column_config={
        "Razão Social": st.column_config.TextColumn("Razão Social", width="large"),
        "Nome Fantasia": st.column_config.TextColumn("Nome Fantasia", width="large"),
        "Município": st.column_config.TextColumn("Município", width="medium"),
        "UF": st.column_config.TextColumn("UF", width="small"),
        "Região": st.column_config.TextColumn("Região", width="medium"),
        "Procedimentos": st.column_config.NumberColumn(
            "Procedimentos", width="medium", format="%d"
        ),
    },
)

col_xlsx, col_pdf, _ = st.columns([1, 1, 4])
with col_xlsx:
    st.download_button(
        "⬇️ Excel",
        data=gerar_excel(
            tabela_com_total,
            "Estabelecimentos",
            filtros=filtros_aplicados,
        ),
        file_name=f"estabelecimentos_{ano_base}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with col_pdf:
    st.download_button(
        "⬇️ PDF",
        data=gerar_pdf(
            tabela_com_total,
            f"Estabelecimentos - SIH/SUS (DATASUS) {ano_base}",
            filtros=filtros_aplicados,
        ),
        file_name=f"estabelecimentos_{ano_base}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

st.markdown('<div class="secao">Procedimentos por mês</div>', unsafe_allow_html=True)
por_mes = df_f.groupby("mes").size().reindex(range(1, 13), fill_value=0)
dados_mes = pd.DataFrame(
    {
        "mes_nome": [settings.MESES_NOME_CURTO[m - 1] for m in por_mes.index],
        "quantidade": por_mes.values,
    }
)
y_max_mes = max(int(dados_mes["quantidade"].max()), 1)
grafico_mes = (
    alt.Chart(dados_mes)
    .mark_bar(color=settings.COR_ACENTO)
    .encode(
        x=alt.X("mes_nome:N", sort=settings.MESES_NOME_CURTO, title=None),
        y=alt.Y(
            "quantidade:Q",
            title=None,
            scale=alt.Scale(domain=[0, y_max_mes * 1.1], nice=False),
        ),
        tooltip=[
            alt.Tooltip("mes_nome:N", title="Mês"),
            alt.Tooltip("quantidade:Q", title="Procedimentos"),
        ],
    )
)
st.altair_chart(grafico_mes, use_container_width=True)

st.markdown(
    '<div class="secao">Procedimentos por categoria</div>',
    unsafe_allow_html=True,
)
por_categoria = df_f.groupby("categoria").size().sort_values(ascending=False)
dados_categoria = pd.DataFrame(
    {
        "categoria": por_categoria.index,
        "quantidade": por_categoria.values,
    }
)
x_max_categoria = max(int(dados_categoria["quantidade"].max()), 1)
grafico_categoria = (
    alt.Chart(dados_categoria)
    .mark_bar(color=settings.COR_ACENTO)
    .encode(
        y=alt.Y("categoria:N", sort="-x", title=None),
        x=alt.X(
            "quantidade:Q",
            title=None,
            scale=alt.Scale(domain=[0, x_max_categoria * 1.1], nice=False),
        ),
        tooltip=[
            alt.Tooltip("categoria:N", title="Categoria"),
            alt.Tooltip("quantidade:Q", title="Procedimentos"),
        ],
    )
)
st.altair_chart(grafico_categoria, use_container_width=True)
