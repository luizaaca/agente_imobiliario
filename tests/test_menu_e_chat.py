"""Regras do menu e da entrada no simulador de chat.

Duas coisas que so existem em tela e por isso escapam facil: a ordem e os
separadores do menu lateral, e o que o simulador faz quando se chega nele.
"""

from dataclasses import dataclass

import pytest
import streamlit as st

from src.ui.estilo import _RAIL_CSS
from src.ui.navegacao import (
    CHAVE_ENTROU_AGORA,
    CHAVE_PAGINA_ANTERIOR,
    entrou_na_pagina_agora,
    marcar_pagina_em_execucao,
)


@dataclass
class PaginaFake:
    """O que `marcar_pagina_em_execucao` usa de uma `st.Page`."""
    url_path: str


@pytest.fixture(autouse=True)
def sessao_limpa():
    for chave in (CHAVE_PAGINA_ANTERIOR, CHAVE_ENTROU_AGORA):
        st.session_state.pop(chave, None)
    yield


# --- Chegada a uma pagina ----------------------------------------------------


def test_primeira_pagina_da_sessao_conta_como_chegada():
    marcar_pagina_em_execucao(PaginaFake("chat"))
    assert entrou_na_pagina_agora()


def test_rerun_na_mesma_pagina_nao_e_chegada():
    """A regra que protege a conversa aberta.

    Cada clique dentro do simulador roda o script inteiro de novo. Se isso
    contasse como entrar na pagina, mandar uma mensagem zeraria a conversa
    que acabou de ser mandada.
    """
    marcar_pagina_em_execucao(PaginaFake("chat"))
    marcar_pagina_em_execucao(PaginaFake("chat"))
    assert not entrou_na_pagina_agora()


def test_voltar_ao_chat_depois_de_sair_e_chegada_de_novo():
    marcar_pagina_em_execucao(PaginaFake("chat"))
    marcar_pagina_em_execucao(PaginaFake("dashboard"))
    marcar_pagina_em_execucao(PaginaFake("chat"))
    assert entrou_na_pagina_agora()


def test_sem_marcacao_nenhuma_nao_ha_chegada():
    assert not entrou_na_pagina_agora()


# --- Separadores do menu -----------------------------------------------------


def test_o_separador_do_menu_usa_o_mesmo_risco_do_rodape():
    """Um segundo tom de cinza leria como dois tipos de corte diferentes."""
    risco = "border-top: 1px solid color-mix(in srgb, currentColor 14%, transparent)"
    assert _RAIL_CSS.count(risco) == 2


def test_o_separador_marca_a_ajuda_e_o_simulador():
    """Escolhidos pelo `href`: a posicao da ajuda muda conforme o papel."""
    assert 'li:has(a[href$="/ajuda"])' in _RAIL_CSS
    assert 'li:has(a[href$="/chat"])' in _RAIL_CSS
