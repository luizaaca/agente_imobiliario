"""Interface de chat simulador do agente SDR."""
import asyncio
import uuid

import streamlit as st

from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

CANAL = "streamlit"


def _prefixo_do_usuario() -> str:
    return f"streamlit_{st.session_state.get('username', 'demo')}_"


def _iniciar_conversa(nova: bool = False) -> None:
    """Resolve qual lead esta sessão do chat representa.

    Cada conversa tem um identificador próprio no external_id. Sem isso todas
    as conversas do mesmo usuário colapsavam em um único lead, e o botão
    "Nova Conversa" reabria sempre o mesmo registro.

    O lead só é criado na primeira mensagem: abrir a aba não deve encher o
    painel do corretor de leads vazios.
    """
    lead_id = None
    historico = []

    if not nova:
        lead_service = LeadService()
        with get_db() as db:
            identidade = lead_service.get_latest_identity_by_prefix(
                CANAL, _prefixo_do_usuario(), db
            )
            if identidade:
                # Retoma a última conversa (ex.: após refresh da página).
                lead_id = identidade.lead_id
                historico = [
                    {"role": m.role, "content": m.content}
                    for m in lead_service.get_history(lead_id, 50, db)
                    if m.role in ("user", "assistant")
                ]

    st.session_state.lead_id = lead_id
    st.session_state.messages = historico


def _garantir_lead() -> int:
    """Cria o lead da conversa no primeiro envio, se ainda não existir."""
    if st.session_state.lead_id is None:
        with get_db() as db:
            lead = LeadService().get_or_create_lead(
                channel=CANAL,
                external_id=f"{_prefixo_do_usuario()}{uuid.uuid4().hex[:8]}",
                db=db,
            )
            st.session_state.lead_id = lead.id
    return st.session_state.lead_id


def render_chat():
    st.header("💬 Chat com o Agente SDR")
    st.caption("Simule uma conversa como lead imobiliário")

    if "lead_id" not in st.session_state:
        _iniciar_conversa()

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Digite sua mensagem..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                lead_id = _garantir_lead()
                deps = SDRDependencies(
                    lead_id=lead_id,
                    channel=CANAL,
                    lead_service=LeadService(),
                    catalog_service=CatalogService(),
                    scheduling_service=SchedulingService(),
                    llm_usage_service=LLMUsageService(),
                )
                response = asyncio.run(
                    process_message(
                        lead_id=lead_id,
                        user_text=prompt,
                        channel=CANAL,
                        deps=deps,
                    )
                )
                st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})

    # Sidebar with lead info
    with st.sidebar:
        st.divider()
        st.subheader("Info do Lead")
        if st.session_state.lead_id is None:
            st.caption("O lead é criado ao enviar a primeira mensagem.")
        else:
            with get_db() as db:
                lead = LeadService().get_lead(st.session_state.lead_id, db)
                if lead:
                    st.write(f"ID: {lead.id}")
                    st.write(f"Status: {lead.status}")
                    st.write(f"Score: {lead.score or 'N/A'}")
        if st.button("🔄 Nova Conversa"):
            _iniciar_conversa(nova=True)
            st.rerun()
