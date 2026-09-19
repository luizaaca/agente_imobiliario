#!/usr/bin/env python3
"""Ponto de entrada principal da aplicação Streamlit.

Inclui autenticação, chat simulador e dashboard do corretor.
"""

import os
import yaml
import streamlit as st
import streamlit_authenticator as stauth

from src.config import settings

st.set_page_config(
    page_title="Agente SDR Imobiliário",
    page_icon="🏠",
    layout="wide",
)

# --- Autenticação ---
try:
    with open("config/credentials.yaml") as f:
        config = yaml.safe_load(f)
    
    config["cookie"]["key"] = settings.AUTH_COOKIE_KEY
    
    authenticator = stauth.Authenticate(
        credentials=config["credentials"],
        cookie_name=config["cookie"]["name"],
        cookie_key=config["cookie"]["key"],
        cookie_expiry_days=config["cookie"]["expiry_days"],
    )
    
    name, authentication_status, username = authenticator.login()
    
    if authentication_status is False:
        st.error("❌ Usuário ou senha incorretos.")
        st.stop()
    
    if authentication_status is None:
        st.warning("🔒 Por favor, faça login para acessar o sistema.")
        st.stop()
    
    # Sidebar
    with st.sidebar:
        st.write(f"👤 **{name}**")
        authenticator.logout("Sair", "sidebar")
        st.divider()
        st.caption("Agente SDR Imobiliário v0.1")
    
    # Tabs
    tab_chat, tab_dashboard = st.tabs(["💬 Chat Simulador", "📊 Dashboard"])
    
    with tab_chat:
        from src.ui.chat import render_chat
        render_chat()
    
    with tab_dashboard:
        from src.ui.dashboard import render_dashboard
        render_dashboard()

except FileNotFoundError:
    st.error("Arquivo config/credentials.yaml não encontrado!")
    st.info("Crie o arquivo de credenciais conforme a documentação.")
    st.stop()
