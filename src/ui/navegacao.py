"""Navegacao entre as paginas da UI.

As paginas sao criadas em `app.py` e registradas aqui. O registro existe para o
dashboard conseguir mandar o usuario para o simulador sem importar o chat — e
sem que os dois modulos se importem em circulo.
"""

from typing import Any, Optional

import streamlit as st

from src.config import settings

# Lead que o dashboard pediu para abrir no simulador. O chat consome e limpa.
CHAVE_CONVERSA_PEDIDA = "conversa_pedida"

_paginas: dict[str, Any] = {}


def registrar_paginas(chat: Any, dashboard: Any) -> None:
    """Guarda as `st.Page` criadas em app.py para uso em `st.switch_page`."""
    _paginas["chat"] = chat
    _paginas["dashboard"] = dashboard


def abrir_conversa_no_simulador(lead_id: int) -> None:
    """Leva o lead para a pagina do chat.

    Chamada no fluxo normal do script (nao em `on_click`), porque
    `st.switch_page` interrompe a execucao para trocar de pagina.
    """
    st.session_state[CHAVE_CONVERSA_PEDIDA] = lead_id
    st.switch_page(_paginas["chat"])


def conversa_pedida() -> Optional[int]:
    """Consome o pedido pendente de abertura de conversa, se houver."""
    return st.session_state.pop(CHAVE_CONVERSA_PEDIDA, None)


# Marca que o balão da chave de cookie já foi mostrado nesta sessão.
CHAVE_AVISO_COOKIE = "aviso_cookie_visto"


def aviso_de_chave_de_cookie_gerada() -> None:
    """Balão dispensável avisando que a chave do cookie foi sorteada.

    Aparece uma vez por sessão: o log registra o alerta para quem opera, e este
    balão existe para quem está usando a tela entender por que pode ser
    deslogado sem motivo aparente depois de um restart.
    """
    if not settings.AUTH_COOKIE_KEY_GERADA:
        return
    if st.session_state.get(CHAVE_AVISO_COOKIE):
        return

    st.session_state[CHAVE_AVISO_COOKIE] = True
    st.toast(
        "`AUTH_COOKIE_KEY` ausente — uma chave temporária foi gerada. "
        "Sua sessão cai a cada reinício da aplicação.",
        icon=":material/key_off:",
    )


def menu_do_usuario(nome: str, authenticator: Any) -> None:
    """Identificacao do usuario no topo a direita, com menu flutuante.

    Fica fora da barra lateral porque la o espaco e da navegacao; o popover
    guarda o que e ocasional (nome completo, versao, sair).
    """
    nome = nome or "Usuário"
    _, coluna = st.columns([5, 1], vertical_alignment="center")
    with coluna, st.popover(
        nome.split()[0], icon=":material/account_circle:", width="stretch"
    ):
        st.markdown(f"**{nome}**")
        st.caption("Agente SDR Imobiliário v0.1")
        st.divider()
        authenticator.logout("Sair", "main", key="logout_menu")
