#!/usr/bin/env python3
"""Ponto de entrada principal da aplicação Streamlit.

Inclui autenticação, chat simulador e dashboard do corretor.
"""

import streamlit as st
import streamlit_authenticator as stauth
import yaml

from src.config import settings
from src.ui.chat import render_chat
from src.ui.dashboard import render_dashboard
from src.ui.navegacao import CHAVE_NAV, PAGINA_CHAT, PAGINAS

st.set_page_config(
    page_title="Agente SDR Imobiliário",
    page_icon="🏠",
    layout="wide",
)

# --- Autenticação ---
try:
    with open("config/credentials.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    st.error("Arquivo config/credentials.yaml não encontrado!")
    st.info("Crie o arquivo de credenciais conforme a documentação.")
    st.stop()

config["cookie"]["key"] = settings.AUTH_COOKIE_KEY

authenticator = stauth.Authenticate(
    credentials=config["credentials"],
    cookie_name=config["cookie"]["name"],
    cookie_key=config["cookie"]["key"],
    cookie_expiry_days=config["cookie"]["expiry_days"],
    auto_hash=False,
)

# streamlit-authenticator >= 0.4: login() renderiza o formulário e grava o
# resultado em st.session_state; não retorna tupla.
authenticator.login()

authentication_status = st.session_state.get("authentication_status")
name = st.session_state.get("name")

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

# Abas com `key` e `on_change="rerun"`: assim o Streamlit guarda a aba ativa em
# session_state, o que permite ao dashboard abrir a conversa de um lead direto
# no simulador, e expoe `.open` — usado abaixo para montar so a aba visivel,
# em vez de rodar as duas consultas a cada interacao.
st.session_state.setdefault(CHAVE_NAV, PAGINA_CHAT)
tab_chat, tab_dashboard = st.tabs(PAGINAS, key=CHAVE_NAV, on_change="rerun")

with tab_chat:
    if tab_chat.open:
        render_chat()

with tab_dashboard:
    if tab_dashboard.open:
        render_dashboard()

with st.sidebar:
    st.divider()
    st.caption("Agente SDR Imobiliário v0.1")
