"""Regras de tela que escapam facil por so existirem desenhadas.

Tres coisas: a ordem e os separadores do menu lateral, o que o simulador faz
quando se chega nele, e o desenho dos botoes de icone da lista de leads — onde
um botao esquecido no CSS vira icone solto, sem alvo de clique nem hover.
"""

import re
from dataclasses import dataclass

import pytest
import streamlit as st

from src.ui.estilo import _RAIL_CSS
from src.ui.leads import ACOES_DA_LISTA
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

# --- Botoes de icone da lista de leads ---------------------------------------


def _regras(css: str) -> list[tuple[str, str]]:
    """(lista de seletores, corpo) de cada regra do CSS."""
    return [
        (casa.group(1).strip(), casa.group(2))
        for casa in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _alcanca(seletores: str, chave: str) -> bool:
    """Se a lista de seletores pega a `key` que a tabela gera: `<chave>_<id>`."""
    return f'[class*="st-key-{chave}_"]' in seletores


def test_toda_acao_da_lista_tem_alvo_de_clique_e_hover():
    """O follow-up ficou de fora do bloco de tamanho e saiu com 16px de
    largura, contra 36 dos vizinhos, sem cor atenuada e sem fundo no hover.

    A tupla de ações é onde se acrescenta botão, e o desenho mora noutro
    arquivo. Sem esta conferência, a próxima ação nasce como ícone solto —
    e isso só aparece olhando a tela.

    Os dois blocos são separados de propósito: estar no de hover não dá
    tamanho, e foi exatamente assim que o defeito passou despercebido.
    """
    regras = _regras(_RAIL_CSS)

    for acao in ACOES_DA_LISTA:
        desenham = [
            corpo for seletores, corpo in regras
            if _alcanca(seletores, acao.chave) and ":hover" not in seletores
        ]
        assert any("width" in corpo for corpo in desenham), (
            f"{acao.chave} sem quadrado de clique"
        )
        assert any(
            _alcanca(seletores, acao.chave) and ":hover" in seletores
            for seletores, _ in regras
        ), f"{acao.chave} sem hover"


def test_excluir_se_afasta_das_outras_acoes_da_linha():
    """Disparar follow-up manda mensagem a uma pessoa; excluir apaga o lead.

    São as duas ações com consequência da linha. Encostadas uma na outra, a
    mão erra de botão.
    """
    regra = re.search(
        r'\.st-key-tabela_de_leads \[class\*="st-key-acao_excluir_"\] button '
        r"\{([^}]*)\}",
        _RAIL_CSS,
    )
    assert regra is not None, "a regra de afastamento sumiu"
    assert "margin-left" in regra.group(1)


def test_a_acao_destrutiva_e_a_ultima_da_linha():
    """O afastamento só separa se excluir estiver na ponta."""
    assert ACOES_DA_LISTA[-1].chave == "acao_excluir"
