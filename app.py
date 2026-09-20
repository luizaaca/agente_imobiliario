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
from src.ui.estilo import aplicar_estilo
from src.ui.navegacao import (
    aviso_de_chave_de_cookie_gerada,
    menu_do_usuario,
    registrar_paginas,
)

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

# Navegação como páginas de verdade: os links ficam na barra lateral recolhível
# e cada página monta só o seu próprio conteúdo. `st.switch_page` é o que
# permite ao dashboard abrir a conversa de um lead direto no simulador.
pagina_chat = st.Page(
    render_chat, title="Chat Simulador", icon="💬", url_path="chat", default=True
)
pagina_dashboard = st.Page(
    render_dashboard, title="Dashboard", icon="📊", url_path="dashboard"
)
registrar_paginas(pagina_chat, pagina_dashboard)

# O dashboard vem primeiro na lista e o simulador por ultimo. A ordem da lista
# e so a ordem dos links: `default=True` no chat continua mandando quem abre a
# aplicacao direto para ele.
navegacao = st.navigation([pagina_dashboard, pagina_chat])

aplicar_estilo()
menu_do_usuario(name, authenticator)
aviso_de_chave_de_cookie_gerada()
navegacao.run()
