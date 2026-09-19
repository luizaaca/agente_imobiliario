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
from src.ui.navegacao import CHAVE_NAV, PAGINA_CHAT, PAGINA_DASHBOARD, PAGINAS

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

    # Radio em vez de st.tabs: o dashboard precisa conseguir mandar o usuario
    # para o simulador ao abrir a conversa de um lead, e aba nao se seleciona
    # por codigo. O `index` nao e passado de proposito: quem manda e a chave
    # em session_state, escrita pelos callbacks de navegacao.
    st.session_state.setdefault(CHAVE_NAV, PAGINA_CHAT)
    pagina = st.radio("Navegação", PAGINAS, key=CHAVE_NAV)
    st.divider()

if pagina == PAGINA_DASHBOARD:
    render_dashboard()
else:
    render_chat()

with st.sidebar:
    st.divider()
    st.caption("Agente SDR Imobiliário v0.1")
