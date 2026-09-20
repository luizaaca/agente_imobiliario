"""Dashboard do corretor: KPIs, distribuicao da carteira e custo de LLM.

Tela de leitura, nao de operacao. O que se faz com um lead — editar, vincular
canal, disparar follow-up, excluir — mora no menu **Leads**; aqui a carteira
existe para ordenar e escolher, e clicar numa linha abre a ficha la.
"""

import pandas as pd
import streamlit as st
from sqlalchemy import func

from src.db.models import Agendamento, FollowUpAttempt, Lead
from src.db.session import get_db
from src.services.llm_usage_service import LLMUsageService
from src.ui.leads import abrir_ficha, temperatura
from src.ui.navegacao import abrir_leads
from src.ui.papeis import e_admin, papeis_da_sessao

# Ordem do funil, para o grafico nao sair em ordem alfabetica — a leitura util
# e a do caminho que o lead percorre.
ORDEM_DO_FUNIL = ["novo", "em_qualificacao", "qualificado", "agendado", "inativo"]


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
    dados = {k.replace("_", " "): contagens.get(k, 0) for k in chaves}
    if contagens.get(None):
        dados["não informado"] = contagens[None]

    return pd.DataFrame({"leads": list(dados.values())}, index=list(dados))


def _distribuicao(db) -> None:
    """Como a carteira se reparte entre estagio do funil e intencao."""
    col_status, col_intencao = st.columns(2)

    with col_status:
        st.markdown("##### Leads por status")
        # `sort=False` mantem a ordem que `_contagem` devolveu. No padrao o
        # Streamlit ordena alfabeticamente, e "agendado, em qualificacao,
        # inativo, novo, qualificado" nao diz nada sobre o funil.
        st.bar_chart(
            _contagem(db, Lead.status, ORDEM_DO_FUNIL),
            horizontal=True,
            sort=False,
        )
    with col_intencao:
        st.markdown("##### Leads por intenção")
        st.bar_chart(_contagem(db, Lead.intencao), horizontal=True)


def _tabela_de_leads(db) -> None:
    """Carteira ordenavel. Clicar numa linha abre a ficha no menu Leads."""
    leads = db.query(Lead).order_by(Lead.score.desc().nullslast()).limit(200).all()
    if not leads:
        st.info("Nenhum lead registrado ainda.")
        return

    tabela = pd.DataFrame(
        [
            {
                "id": lead.id,
                "Lead": lead.nome or f"Lead {lead.id}",
                "Status": lead.status.replace("_", " "),
                "Temperatura": temperatura(float(lead.score or 0))[1],
                "Intenção": lead.intencao or "—",
                "Região": lead.regiao_interesse or lead.bairro_interesse or "—",
                "Score": float(lead.score) if lead.score is not None else None,
            }
            for lead in leads
        ]
    )

    st.subheader("Carteira")
    st.caption(
        "Ordene clicando no cabeçalho da coluna. Clique em uma linha para "
        "abrir a ficha do lead."
    )
    selecao = st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_order=("Lead", "Status", "Temperatura", "Intenção", "Região", "Score"),
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=10, format="%.1f"
            ),
        },
    )

    escolhidas = selecao["selection"]["rows"]
    if escolhidas:
        abrir_ficha(int(tabela.iloc[escolhidas[0]]["id"]))
        abrir_leads()


def render_dashboard():
    st.header("Dashboard do Corretor", divider="gray")

    with get_db() as db:
        _kpis(db)
        _painel_de_custo(db)
        st.divider()
        _distribuicao(db)
        st.divider()
        _tabela_de_leads(db)
