"""Dashboard do corretor com KPIs, leads e agendamentos."""
import streamlit as st
from sqlalchemy import desc, func

from src.db.models import Agendamento, Lead
from src.db.session import get_db


def render_dashboard():
    st.header("📊 Dashboard do Corretor")
    
    with get_db() as db:
        # KPIs
        total_leads = db.query(func.count(Lead.id)).scalar() or 0
        leads_quentes = db.query(func.count(Lead.id)).filter(Lead.score >= 7).scalar() or 0
        agendamentos = db.query(func.count(Agendamento.id)).filter(Agendamento.status == 'pendente').scalar() or 0
        leads_inativos = db.query(func.count(Lead.id)).filter(Lead.status == 'inativo').scalar() or 0
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total de Leads", total_leads)
        with col2:
            st.metric("🔥 Leads Quentes", leads_quentes)
        with col3:
            st.metric("📅 Agendamentos", agendamentos)
        with col4:
            st.metric("💤 Inativos", leads_inativos)
        
        st.divider()
        
        # Filters
        col_filter1, col_filter2, col_filter3 = st.columns(3)
        with col_filter1:
            busca = st.text_input("🔍 Buscar", placeholder="Nome, bairro, intenção...")
        with col_filter2:
            status_filter = st.selectbox("Status", ["Todos", "novo", "em_qualificacao", "qualificado", "agendado", "inativo"])
        with col_filter3:
            intencao_filter = st.selectbox("Intenção", ["Todas", "compra", "aluguel", "investimento"])
        
        # Build query
        query = db.query(Lead).order_by(desc(Lead.score))
        if status_filter != "Todos":
            query = query.filter(Lead.status == status_filter)
        if intencao_filter != "Todas":
            query = query.filter(Lead.intencao == intencao_filter)
        if busca:
            search_term = f"%{busca}%"
            query = query.filter(
                (Lead.nome.ilike(search_term)) |
                (Lead.bairro_interesse.ilike(search_term)) |
                (Lead.perfil_narrativo.ilike(search_term))
            )
        
        leads = query.limit(50).all()
        
        if not leads:
            st.info("Nenhum lead encontrado com os filtros selecionados.")
            return
        
        # Lead list
        st.subheader(f"Leads ({len(leads)})")
        for lead in leads:
            score_emoji = "🔴" if (lead.score or 0) >= 7 else "🟠" if (lead.score or 0) >= 4 else "⚪"
            with st.expander(f"{score_emoji} {lead.nome or f'Lead {lead.id}'} | {lead.status} | Score: {lead.score or 'N/A'}"):
                col_info, col_actions = st.columns([3, 1])
                with col_info:
                    st.write(f"**Intenção:** {lead.intencao or 'N/I'}")
                    st.write(f"**Região:** {lead.regiao_interesse or lead.bairro_interesse or 'N/I'}")
                    st.write(f"**Orçamento:** R$ {lead.orcamento_min or '?'} a R$ {lead.orcamento_max or '?'}")
                    st.write(f"**Quartos:** {lead.quartos or 'N/I'}")
                    st.write(f"**Urgência:** {lead.urgencia or 'N/I'}")
                    
                    if lead.perfil_narrativo:
                        st.subheader("Perfil Narrativo")
                        st.markdown(lead.perfil_narrativo)
                    
                    if lead.resumo:
                        st.subheader("Resumo Executivo")
                        st.markdown(lead.resumo)
                
                with col_actions:
                    st.button("📞 Agendar Ligação", key=f"call_{lead.id}")
                    st.button("🔄 Follow-up", key=f"followup_{lead.id}")
