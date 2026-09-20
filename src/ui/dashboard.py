"""Dashboard do corretor: KPIs, distribuicao da carteira e custo de LLM.

Tela de leitura, nao de operacao. O que se faz com um lead — editar, vincular
canal, disparar follow-up, excluir — mora no menu **Leads**; aqui a carteira
existe para ordenar e escolher, e a lupa de cada linha abre a ficha la.
"""

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import func

from src.db.models import Agendamento, FollowUpAttempt, Lead
from src.db.session import get_db
from src.services.llm_usage_service import LLMUsageService
from src.ui.leads import COR_DO_STATUS, abrir_ficha, temperatura
from src.ui.papeis import e_admin, papeis_da_sessao
from src.ui.tabela import (
    Acao,
    Coluna,
    aplicar_ordem,
    rotulo_do_lead,
    seletor_de_ordem,
    tabela_de_leads,
    texto,
)
from src.ui.texto import markdown_seguro

# Ordem do funil, para o grafico nao sair em ordem alfabetica — a leitura util
# e a do caminho que o lead percorre.
ORDEM_DO_FUNIL = ["novo", "em_qualificacao", "qualificado", "agendado", "inativo"]

NAO_INFORMADO = "não informado"
CINZA_NEUTRO = "#CBD5E1"

# As cores do funil sao as mesmas dos selos de status na ficha do lead: o
# mesmo estagio tem a mesma cor em toda a aplicacao, entao o grafico se le sem
# consultar legenda. A progressao vai do amarelo (entrou agora) ao verde
# (agendou), com o cinza do inativo fora dela.
CORES_DO_FUNIL = {
    "novo": "#EAB308",
    "em qualificacao": "#8B5CF6",
    "qualificado": "#3B82F6",
    "agendado": "#22C55E",
    "inativo": "#94A3B8",
    NAO_INFORMADO: CINZA_NEUTRO,
}

# Intencao nao tem progressao, entao as cores so precisam se distinguir entre
# si e nao colidir com as do funil.
CORES_DA_INTENCAO = {
    "compra": "#6366F1",
    "aluguel": "#06B6D4",
    "investimento": "#F59E0B",
    NAO_INFORMADO: CINZA_NEUTRO,
}


def _alerta_de_budget(resumo: dict) -> None:
    """Avisa, fora do painel recolhido, quando o teto de tokens estourou.

    Dentro de um expander fechado o aviso nao existe na pratica: quem abre o
    dashboard com o orcamento estourado veria uma tela normal e so descobriria
    o bloqueio quando o chat parasse de responder.
    """
    if resumo["monthly_budget_exceeded"]:
        st.error(
            "**Orçamento mensal de LLM esgotado.** Conversas novas recebem "
            "mensagem de indisponibilidade até a virada do mês ou até "
            "`LLM_MONTHLY_TOKEN_BUDGET` subir.",
            icon=":material/credit_card_off:",
        )
    elif resumo["daily_budget_exceeded"]:
        st.warning(
            "**Orçamento diário de LLM esgotado.** O chat e o follow-up ficam "
            "bloqueados até amanhã, ou até `LLM_DAILY_TOKEN_BUDGET` subir.",
            icon=":material/schedule:",
        )


def _saude_do_agente(resumo: dict) -> None:
    """Tempo de resposta e taxa de erro do provider, hoje.

    Ambos sao `None` enquanto nao houve chamada nenhuma no dia, e a tela
    mostra "—": um zero ali afirmaria que esta tudo bem quando na verdade nada
    foi exercitado.
    """
    latencia = resumo["daily_latency_ms"]
    taxa = resumo["daily_error_rate"]

    col_tempo, col_erro = st.columns(2)
    col_tempo.metric(
        "Tempo médio de resposta",
        f"{latencia / 1000:.1f} s" if latencia is not None else "—",
        help="Média das chamadas bem-sucedidas ao provider hoje.",
    )
    col_erro.metric(
        "Taxa de erro",
        f"{taxa:.0%}" if taxa is not None else "—",
        help="Chamadas que falharam sobre o total de chamadas de hoje.",
    )


def _painel_de_custo(db) -> None:
    """Consumo de LLM do dia e do mes, com o quanto falta para o teto.

    So para o admin: o custo em dolar do provider e informacao de quem opera a
    aplicacao, nao de quem atende leads. O alerta de estouro, esse, aparece
    para todos os papeis — ele explica por que o chat parou de responder.
    """
    resumo = LLMUsageService().get_dashboard_summary(db)
    _alerta_de_budget(resumo)

    if not e_admin(papeis_da_sessao()):
        return

    with st.expander("Consumo de LLM", expanded=False, icon=":material/payments:"):
        _saude_do_agente(resumo)
        st.divider()
        col_dia, col_mes = st.columns(2)
        for coluna, periodo, rotulo in (
            (col_dia, "daily", "Hoje"),
            (col_mes, "monthly", "Este mês"),
        ):
            tokens = resumo[f"{periodo}_tokens"]
            teto = resumo[f"{periodo}_budget"]
            custo = float(resumo[f"{periodo}_cost_usd"])
            with coluna:
                st.metric(f"{rotulo} — tokens", f"{tokens:,}".replace(",", "."))
                st.progress(
                    min(tokens / teto, 1.0) if teto else 0.0,
                    text=f"{tokens:,} de {teto:,} do orçamento".replace(",", "."),
                )
                st.metric(f"{rotulo} — custo estimado", f"US$ {custo:.4f}")

        st.caption(
            "Custo estimado pela tabela de preços por modelo em "
            "`LLMUsageService.PRICING`; modelos fora da tabela usam um preço "
            "genérico e registram aviso no log."
        )


def _kpis(db) -> None:
    total_leads = db.query(func.count(Lead.id)).scalar() or 0
    leads_quentes = db.query(func.count(Lead.id)).filter(Lead.score >= 7).scalar() or 0
    agendamentos = (
        db.query(func.count(Agendamento.id))
        .filter(Agendamento.status == "pendente")
        .scalar() or 0
    )
    leads_inativos = (
        db.query(func.count(Lead.id)).filter(Lead.status == "inativo").scalar() or 0
    )
    # So as tentativas que sairam de fato: uma mensagem gerada sem canal ativo
    # aparece no painel, mas nao foi disparada para ninguem.
    followups = (
        db.query(func.count(FollowUpAttempt.id))
        .filter(FollowUpAttempt.status == "sent")
        .scalar() or 0
    )

    # `border=True` fecha cada numero em um cartao: sem a borda os cinco viram
    # texto solto no topo da pagina, sem separacao entre eles.
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total de leads", total_leads, icon=":material/group:", border=True)
    col2.metric(
        "Leads quentes",
        leads_quentes,
        icon=":material/local_fire_department:",
        border=True,
    )
    col3.metric("Agendamentos", agendamentos, icon=":material/event:", border=True)
    # Rotulo curto: "Follow-ups enviados" nao cabe em um quinto da largura e o
    # Streamlit o corta no meio da palavra. O que ele conta fica no `help`.
    col4.metric(
        "Follow-ups",
        followups,
        icon=":material/send:",
        border=True,
        help="Tentativas efetivamente despachadas por um canal com envio ativo.",
    )
    col5.metric("Inativos", leads_inativos, icon=":material/bedtime:", border=True)


def _contagem(db, coluna, ordem: list[str] | None = None) -> pd.DataFrame:
    """Quantos leads por valor de uma coluna, pronto para o grafico.

    O valor nulo vira "não informado" em vez de sumir: um lead sem intencao e
    justamente o que ainda precisa ser qualificado, e some-lo da barra
    esconderia o trabalho que falta.
    """
    contagens = dict(db.query(coluna, func.count(Lead.id)).group_by(coluna).all())

    chaves = ordem if ordem else sorted(k for k in contagens if k is not None)
    linhas = [
        {"categoria": chave.replace("_", " "), "leads": contagens.get(chave, 0)}
        for chave in chaves
    ]
    if contagens.get(None):
        linhas.append({"categoria": NAO_INFORMADO, "leads": contagens[None]})

    return pd.DataFrame(linhas)


def _grafico(dados: pd.DataFrame, cores: dict[str, str]) -> alt.Chart:
    """Barras horizontais com uma cor por categoria.

    Altair, e nao `st.bar_chart`, porque so aqui da para fixar qual cor cai em
    qual categoria: no `st.bar_chart` a paleta e atribuida na ordem em que os
    valores aparecem, entao `qualificado` mudaria de cor conforme a carteira
    mudasse — e a cor deixaria de significar alguma coisa.

    `sort=None` preserva a ordem do DataFrame, que no funil e a do caminho que
    o lead percorre.
    """
    categorias = list(dados["categoria"])
    return (
        alt.Chart(dados)
        .mark_bar(cornerRadiusEnd=5, height=22)
        .encode(
            y=alt.Y("categoria:N", sort=None, title=None),
            x=alt.X(
                "leads:Q",
                title=None,
                axis=alt.Axis(tickMinStep=1, format="d", grid=True),
            ),
            color=alt.Color(
                "categoria:N",
                scale=alt.Scale(
                    domain=categorias,
                    range=[cores.get(c, CINZA_NEUTRO) for c in categorias],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("categoria:N", title=" "),
                alt.Tooltip("leads:Q", title="Leads"),
            ],
        )
        .properties(height=alt.Step(30))
    )


def _distribuicao(db) -> None:
    """Como a carteira se reparte entre estagio do funil e intencao."""
    col_status, col_intencao = st.columns(2)

    with col_status:
        st.markdown("##### Leads por status")
        st.altair_chart(
            _grafico(_contagem(db, Lead.status, ORDEM_DO_FUNIL), CORES_DO_FUNIL),
            use_container_width=True,
        )
    with col_intencao:
        st.markdown("##### Leads por intenção")
        st.altair_chart(
            _grafico(_contagem(db, Lead.intencao), CORES_DA_INTENCAO),
            use_container_width=True,
        )


def _selo_de_score(lead: Lead) -> str:
    """Score com o selo de temperatura, que traduz o numero em uma palavra."""
    if lead.score is None:
        return "—"
    score = float(lead.score)
    cor, palavra = temperatura(score)
    return f"**{score:.1f}** :{cor}-badge[{palavra}]"


COLUNAS_DA_CARTEIRA = (
    Coluna(
        "Lead", 3,
        lambda lead: f"**{markdown_seguro(rotulo_do_lead(lead))}**",
    ),
    Coluna(
        "Status", 3,
        lambda lead: f":{COR_DO_STATUS.get(lead.status, 'gray')}-badge"
                     f"[{lead.status.replace('_', ' ')}]",
    ),
    Coluna("Intenção", 2, lambda lead: texto(lead.intencao)),
    Coluna(
        "Região", 3,
        lambda lead: texto(lead.regiao_interesse or lead.bairro_interesse),
    ),
    Coluna("Score", 3, _selo_de_score),
)

ACOES_DA_CARTEIRA = (
    Acao(
        ":material/search:", "Abrir a ficha deste lead", "acao_abrir",
        lambda lead: abrir_ficha(lead.id),
    ),
)


def _tabela_de_leads(db) -> None:
    """Carteira do corretor, com a lupa levando a ficha no menu Leads.

    Mesmas linhas e mesmos selos da listagem de Leads, so que sem as acoes de
    escrita: aqui e tela de leitura. Montada com colunas, e nao com
    `st.dataframe`, porque a celula do dataframe e desenhada em canvas e nao
    comporta um botao — a lupa como link de celula chegou a ser tentada e nao
    registrava o clique.
    """
    st.subheader("Carteira")

    col_ordem, _ = st.columns([2, 4])
    with col_ordem:
        campo, decrescente = seletor_de_ordem("ordem_da_carteira")

    leads = aplicar_ordem(db.query(Lead), campo, decrescente).limit(200).all()
    if not leads:
        st.info("Nenhum lead registrado ainda.")
        return

    st.caption("A lupa abre a ficha do lead no menu Leads.")
    tabela_de_leads(leads, COLUNAS_DA_CARTEIRA, ACOES_DA_CARTEIRA, peso_das_acoes=1)


def render_dashboard():
    st.header("Dashboard do Corretor", divider="gray")

    with get_db() as db:
        _kpis(db)
        _painel_de_custo(db)
        st.divider()
        _distribuicao(db)
        st.divider()
        _tabela_de_leads(db)
