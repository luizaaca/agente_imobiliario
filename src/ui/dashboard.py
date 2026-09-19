"""Dashboard do corretor com KPIs, custo de LLM, leads e conversas."""
import streamlit as st
from sqlalchemy import desc, func

from src.db.models import Agendamento, Lead
from src.db.session import get_db
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.ui.navegacao import abrir_conversa_no_simulador

# Guarda o id do lead cujo botao de excluir foi clicado, para que o segundo
# clique — o que apaga de verdade — seja deliberado.
CHAVE_EXCLUSAO = "lead_a_excluir"

STATUS_DISPONIVEIS = [
    "Todos", "novo", "em_qualificacao", "qualificado", "agendado", "inativo",
]
ROTULO_DO_TIPO = {
    "followup": "🔄 follow-up automático",
    "handover": "🤝 handover ao corretor",
    "system_notice": "⚙️ aviso do sistema",
}


def _painel_de_custo(db) -> None:
    """Consumo de LLM do dia e do mes, com o quanto falta para o teto."""
    resumo = LLMUsageService().get_dashboard_summary(db)

    with st.expander("💰 Consumo de LLM", expanded=False):
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

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de Leads", total_leads)
    col2.metric("🔥 Leads Quentes", leads_quentes)
    col3.metric("📅 Agendamentos", agendamentos)
    col4.metric("💤 Inativos", leads_inativos)


def _leads_filtrados(db) -> list[Lead]:
    col1, col2, col3 = st.columns(3)
    with col1:
        busca = st.text_input("🔍 Buscar", placeholder="Nome, bairro, intenção...")
    with col2:
        status_filtro = st.selectbox("Status", STATUS_DISPONIVEIS)
    with col3:
        intencao_filtro = st.selectbox(
            "Intenção", ["Todas", "compra", "aluguel", "investimento"]
        )

    query = db.query(Lead).order_by(desc(Lead.score))
    if status_filtro != "Todos":
        query = query.filter(Lead.status == status_filtro)
    if intencao_filtro != "Todas":
        query = query.filter(Lead.intencao == intencao_filtro)
    if busca:
        termo = f"%{busca}%"
        query = query.filter(
            Lead.nome.ilike(termo)
            | Lead.bairro_interesse.ilike(termo)
            | Lead.perfil_narrativo.ilike(termo)
        )
    return query.limit(50).all()


def _mostrar_conversa(lead: Lead, db) -> None:
    """Conversa do lead, do jeito que ela aconteceu."""
    mensagens = LeadService().get_history(lead.id, 200, db)
    if not mensagens:
        st.caption("Nenhuma mensagem registrada para este lead.")
        return

    for msg in mensagens:
        if msg.role not in ("user", "assistant"):
            continue
        with st.chat_message(msg.role):
            rotulo = ROTULO_DO_TIPO.get(msg.message_type)
            if rotulo:
                st.caption(rotulo)
            st.markdown(msg.content)


def _mostrar_agendamentos(lead: Lead, db) -> None:
    agendamentos = SchedulingService().list_by_lead(lead.id, db)
    if not agendamentos:
        return
    st.write("**Agendamentos**")
    for ag in agendamentos:
        imovel = f" — {ag.imovel.titulo} (imóvel #{ag.imovel.id})" if ag.imovel else ""
        st.write(
            f"- {ag.tipo} em {ag.data_hora:%d/%m/%Y %H:%M} [{ag.status}]{imovel}"
        )


def _acoes_do_lead(lead: Lead) -> None:
    # Fora de `on_click` de proposito: `abrir_conversa_no_simulador` termina em
    # `st.switch_page`, que interrompe a execucao para trocar de pagina.
    if st.button(
        "💬 Abrir no simulador",
        key=f"abrir_{lead.id}",
        width="stretch",
        help="Carrega esta conversa no chat para você continuar de onde parou.",
    ):
        abrir_conversa_no_simulador(lead.id)

    if st.session_state.get(CHAVE_EXCLUSAO) != lead.id:
        if st.button("🗑️ Excluir lead", key=f"excluir_{lead.id}", width="stretch"):
            st.session_state[CHAVE_EXCLUSAO] = lead.id
            st.rerun()
        return

    st.warning(f"Excluir o lead {lead.id} e todas as suas mensagens?")
    col_sim, col_nao = st.columns(2)
    if col_sim.button("Confirmar", key=f"confirma_{lead.id}", type="primary"):
        with get_db() as db:
            LeadService().delete_lead(lead.id, db)
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        # A conversa aberta no simulador pode ser justamente esta.
        if st.session_state.get("lead_id") == lead.id:
            st.session_state.lead_id = None
            st.session_state.messages = []
        st.rerun()
    if col_nao.button("Cancelar", key=f"cancela_{lead.id}"):
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        st.rerun()


def render_dashboard():
    st.header("📊 Dashboard do Corretor")

    with get_db() as db:
        _kpis(db)
        _painel_de_custo(db)
        st.divider()

        leads = _leads_filtrados(db)
        if not leads:
            st.info("Nenhum lead encontrado com os filtros selecionados.")
            return

        st.subheader(f"Leads ({len(leads)})")
        for lead in leads:
            score = float(lead.score or 0)
            emoji = "🔴" if score >= 7 else "🟠" if score >= 4 else "⚪"
            nome = lead.nome or f"Lead {lead.id}"
            marcador = lead.score if lead.score is not None else "N/A"
            with st.expander(f"{emoji} {nome} | {lead.status} | Score: {marcador}"):
                col_info, col_acoes = st.columns([3, 1])

                with col_info:
                    st.write(f"**Intenção:** {lead.intencao or 'N/I'}")
                    regiao = lead.regiao_interesse or lead.bairro_interesse or "N/I"
                    st.write(f"**Região:** {regiao}")
                    st.write(
                        f"**Orçamento:** R$ {lead.orcamento_min or '?'} "
                        f"a R$ {lead.orcamento_max or '?'}"
                    )
                    st.write(f"**Quartos:** {lead.quartos or 'N/I'}")
                    st.write(f"**Urgência:** {lead.urgencia or 'N/I'}")

                    if lead.perfil_narrativo:
                        st.write("**Perfil Narrativo**")
                        st.markdown(lead.perfil_narrativo)
                    if lead.resumo:
                        st.write("**Resumo Executivo**")
                        st.markdown(lead.resumo)

                    _mostrar_agendamentos(lead, db)

                with col_acoes:
                    _acoes_do_lead(lead)

                # A conversa fica atras de um toggle: sem isso o Streamlit
                # montaria o historico inteiro dos 50 leads a cada recarga.
                if st.toggle("💬 Ver conversa", key=f"conversa_{lead.id}"):
                    _mostrar_conversa(lead, db)
