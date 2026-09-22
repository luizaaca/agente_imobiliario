#!/usr/bin/env python3
"""Ponto de entrada principal da aplicação Streamlit.

Autenticação, montagem do menu conforme o papel do usuário e navegação entre
dashboard, CRUD de leads e chat simulador.
"""

import streamlit as st
import streamlit_authenticator as stauth
import yaml

from src.config import settings
from src.ui.ajuda import render_ajuda
from src.ui.chat import render_chat
from src.ui.dashboard import render_dashboard
from src.ui.estilo import aplicar_estilo
from src.ui.leads import render_ficha, render_leads
from src.ui.login import tela_de_login
from src.ui.navegacao import (
    aviso_de_chave_de_cookie_gerada,
    marcar_pagina_em_execucao,
    menu_do_usuario,
    registrar_paginas,
)
from src.ui.papeis import menu_do_papel, papeis_da_sessao

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
if tela_de_login(authenticator) is not True:
    st.stop()

name = st.session_state.get("name")

# Navegação como páginas de verdade: os links ficam na barra lateral recolhível
# e cada página monta só o seu próprio conteúdo. `st.switch_page` é o que
# permite ao dashboard abrir a conversa de um lead direto no simulador.
# Pagina inicial em qualquer papel: quem abre a aplicacao cai no painel, nao
# no simulador.
pagina_dashboard = st.Page(
    render_dashboard,
    title="Dashboard",
    icon=":material/space_dashboard:",
    url_path="dashboard",
    default=True,
)
pagina_leads = st.Page(
    render_leads,
    title="Leads",
    icon=":material/contacts:",
    url_path="leads",
)
# A ficha e pagina de verdade, com URL propria, mas fora do menu: e o que faz
# o link "Leads" devolver a listagem quando se esta dentro de uma ficha.
pagina_ficha = st.Page(
    render_ficha,
    title="Ficha do lead",
    icon=":material/contacts:",
    url_path="lead",
    visibility="hidden",
)
pagina_chat = st.Page(
    render_chat,
    title="Simulador de Chat",
    icon=":material/forum:",
    url_path="chat",
)
pagina_ajuda = st.Page(
    render_ajuda,
    title="Ajuda",
    icon=":material/help:",
    url_path="ajuda",
)
registrar_paginas(pagina_chat, pagina_dashboard, pagina_leads, pagina_ficha)

# O menu depende do papel: o simulador e ferramenta de teste e so aparece
# para o admin. Ver `src/ui/papeis.py` — isto e separacao de telas, nao
# fronteira de seguranca.
navegacao = st.navigation(
    menu_do_papel(
        pagina_dashboard,
        pagina_leads,
        pagina_chat,
        pagina_ajuda,
        papeis_da_sessao(),
        pagina_ficha,
    )
)

aplicar_estilo()
menu_do_usuario(name, authenticator)
aviso_de_chave_de_cookie_gerada()
# Antes de desenhar: e o que permite a uma tela saber que a navegacao acabou
# de chegar nela, e nao que ela rodou de novo por um clique seu.
marcar_pagina_em_execucao(navegacao)
navegacao.run()
