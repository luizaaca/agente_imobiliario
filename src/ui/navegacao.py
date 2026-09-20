"""Navegacao entre as paginas da UI.

As paginas sao criadas em `app.py` e registradas aqui. O registro existe para o
dashboard conseguir mandar o usuario para a ficha do lead sem importar a pagina
de leads inteira — e sem que os dois modulos se importem em circulo.
"""

from typing import Any

import streamlit as st

from src.config import settings

_paginas: dict[str, Any] = {}


def registrar_paginas(chat: Any, dashboard: Any, leads: Any) -> None:
    """Guarda as `st.Page` criadas em app.py para uso em `st.switch_page`."""
    _paginas["chat"] = chat
    _paginas["dashboard"] = dashboard
    _paginas["leads"] = leads


def abrir_leads() -> None:
    """Leva quem clicou para o menu de leads.

    Chamada no fluxo normal do script (nao em `on_click`), porque
    `st.switch_page` interrompe a execucao para trocar de pagina. Qual lead
    abrir ja foi guardado na sessao por `leads.abrir_ficha`.
    """
    st.switch_page(_paginas["leads"])


# Marca que o balão da chave de cookie já foi mostrado nesta sessão.
CHAVE_AVISO_COOKIE = "aviso_cookie_visto"


def aviso_de_chave_de_cookie_gerada() -> None:
    """Balão dispensável avisando que a chave do cookie foi sorteada.

    Aparece uma vez por sessão: o log registra o alerta para quem opera, e este
    balão existe para quem está usando a tela entender por que pode ser
    deslogado sem motivo aparente depois de um restart.

    O texto diz explicitamente que dá para seguir assim — não é um erro, é uma
    escolha com um custo conhecido. Os detalhes ficam no README, não aqui.
    """
    if not settings.AUTH_COOKIE_KEY_GERADA:
        return
    if st.session_state.get(CHAVE_AVISO_COOKIE):
        return

    st.session_state[CHAVE_AVISO_COOKIE] = True
    st.toast(
        "Variável de ambiente `AUTH_COOKIE_KEY` ausente — uma chave temporária "
        "foi gerada. **Pode usar assim**, com uma limitação: a sessão cai a "
        "cada reinício da aplicação. Para fixá-la, veja a seção "
        "**Configuração** do README.",
        icon=":material/key_off:",
    )


def menu_do_usuario(nome: str, authenticator: Any) -> None:
    """Identificacao do usuario no rodape da barra lateral, com menu flutuante.

    Quem esta logado e chrome da aplicacao, nao conteudo da tela: no corpo da
    pagina o avatar disputava espaco com o titulo e empurrava a pagina para
    baixo. No pe da barra ele fica junto da navegacao, e com a barra recolhida
    sobra so o avatar, alinhado com os icones — o CSS do rail cuida disso.

    O popover guarda o que e ocasional: nome completo, versao e sair.
    """
    nome = nome or "Usuário"
    with st.sidebar, st.popover(
        nome.split()[0], icon=":material/account_circle:", width="stretch"
    ):
        st.markdown(f"**{nome}**")
        st.caption("Agente SDR Imobiliário v0.1")
        st.divider()
        authenticator.logout("Sair", "main", key="logout_menu")
