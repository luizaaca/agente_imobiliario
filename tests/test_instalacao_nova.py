"""Toda página desenha numa instalação recém-clonada, sem nenhum lead.

É a primeira coisa que quem avalia a POC vê depois do login. O dashboard
quebrava ali com `KeyError: 'categoria'`: sem lead, a distribuição por
intenção virava um DataFrame sem colunas. Com a carteira de desenvolvimento
cheia, nada disso aparecia.
"""

import pytest
from streamlit.testing.v1 import AppTest


def _dashboard():
    from src.ui.dashboard import render_dashboard

    render_dashboard()


def _leads():
    from src.ui.leads import render_leads

    render_leads()


def _ajuda():
    from src.ui.ajuda import render_ajuda

    render_ajuda()


def _chat():
    from src.ui.chat import render_chat

    render_chat()


def _ficha_nova():
    """O botão de novo lead: a ficha em branco, o caminho de quem não tem LLM."""
    import streamlit as st

    from src.ui.leads import CHAVE_LEAD_ABERTO, render_ficha

    st.session_state[CHAVE_LEAD_ABERTO] = 0
    render_ficha()


@pytest.mark.parametrize("pagina", [_dashboard, _leads, _ajuda, _chat, _ficha_nova])
@pytest.mark.parametrize("papel", ["admin", "corretor"])
def test_pagina_desenha_sem_nenhum_lead(db, pagina, papel):
    app = AppTest.from_function(pagina, default_timeout=30)
    app.session_state["roles"] = [papel]
    app.session_state["name"] = "Avaliador"

    app.run()

    assert not app.exception, app.exception
