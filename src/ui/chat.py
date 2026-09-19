"""Interface de chat simulador do agente SDR."""
import asyncio
import streamlit as st
from src.db.session import get_db
from src.services.lead_service import LeadService
from src.services.catalog_service import CatalogService
from src.services.scheduling_service import SchedulingService
from src.services.llm_usage_service import LLMUsageService
from src.agent.sdr_agent import process_message, SDRDependencies

def render_chat():
    st.header("💬 Chat com o Agente SDR")
    st.caption("Simule uma conversa como lead imobiliário")
    
    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "lead_id" not in st.session_state:
        # Create a new lead for the chat session
        with get_db() as db:
            lead_service = LeadService()
            lead = lead_service.get_or_create_lead(
                channel="streamlit",
                external_id=f"streamlit_{st.session_state.get('username', 'demo')}",
                db=db,
            )
            st.session_state.lead_id = lead.id
    
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
                # Create dependencies
                deps = SDRDependencies(
                    lead_id=st.session_state.lead_id,
                    channel="streamlit",
                    lead_service=LeadService(),
                    catalog_service=CatalogService(),
                    scheduling_service=SchedulingService(),
                    llm_usage_service=LLMUsageService(),
                )
                
                # Process message
                response = asyncio.run(
                    process_message(
                        lead_id=st.session_state.lead_id,
                        user_text=prompt,
                        channel="streamlit",
                        deps=deps,
                    )
                )
                st.markdown(response)
        
        st.session_state.messages.append({"role": "assistant", "content": response})
    
    # Sidebar with lead info
    with st.sidebar:
        st.divider()
        st.subheader("Info do Lead")
        with get_db() as db:
            lead_service = LeadService()
            lead = lead_service.get_lead(st.session_state.lead_id, db)
            if lead:
                st.write(f"ID: {lead.id}")
                st.write(f"Status: {lead.status}")
                st.write(f"Score: {lead.score or 'N/A'}")
                if st.button("🔄 Nova Conversa"):
                    st.session_state.messages = []
                    del st.session_state.lead_id
                    st.rerun()
