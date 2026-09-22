"""Navegacao entre as paginas da UI.

As paginas sao criadas em `app.py` e registradas aqui. O registro existe para o
dashboard conseguir mandar o usuario para a ficha do lead sem importar a pagina
de leads inteira — e sem que os dois modulos se importem em circulo.
"""

from typing import Any

import streamlit as st

from src.config import settings
from src.ui.papeis import papeis_da_sessao

_paginas: dict[str, Any] = {}


def registrar_paginas(chat: Any, dashboard: Any, leads: Any, ficha: Any) -> None:
    """Guarda as `st.Page` criadas em app.py para uso em `st.switch_page`."""
    _paginas["chat"] = chat
    _paginas["dashboard"] = dashboard
    _paginas["leads"] = leads
    _paginas["ficha"] = ficha


# As duas funcoes abaixo sao chamadas no fluxo normal do script, e nunca em
# `on_click`: `st.switch_page` interrompe a execucao para trocar de pagina.


def abrir_lista_de_leads() -> None:
    """Volta para a listagem de leads."""
    st.switch_page(_paginas["leads"])


def abrir_pagina_da_ficha() -> None:
    """Abre a ficha do lead que ja foi escolhido na sessao.

    Lista e ficha sao paginas de verdade, com URLs proprias, e nao dois estados
    da mesma tela. E o que faz o link "Leads" do menu devolver a listagem: de
    dentro da ficha ele leva a outra pagina, sem heuristica nenhuma para
    adivinhar se o clique veio do menu ou de um botao da propria tela.
    """
    st.switch_page(_paginas["ficha"])


# Página que o rerun anterior desenhou, e se este rerun é a chegada a uma
# página nova. O Streamlit não tem evento de entrada em página: o script
# inteiro roda de novo a cada clique, e de dentro da tela um rerun por botão é
# indistinguível de uma chegada pelo menu.
CHAVE_PAGINA_ANTERIOR = "pagina_anterior"
CHAVE_ENTROU_AGORA = "entrou_na_pagina_agora"


def marcar_pagina_em_execucao(pagina: Any) -> None:
    """Registra qual página este rerun vai desenhar.

    Chamada em `app.py`, antes de `navegacao.run()`: é o único ponto que sabe
    qual página o `st.navigation` escolheu.
    """
    anterior = st.session_state.get(CHAVE_PAGINA_ANTERIOR)
    st.session_state[CHAVE_PAGINA_ANTERIOR] = pagina.url_path
    st.session_state[CHAVE_ENTROU_AGORA] = anterior != pagina.url_path


def entrou_na_pagina_agora() -> bool:
    """Verdadeiro quando a navegação acabou de chegar à página deste rerun."""
    return bool(st.session_state.get(CHAVE_ENTROU_AGORA))


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

    O popover guarda o que e ocasional: nome completo, papel, versao e sair.

    `type="tertiary"` deixa o gatilho sem borda nem preenchimento: no pe da
    barra ele e um rodape discreto, e um botao desenhado ali competiria com os
    links de navegacao logo acima, que sao o que a barra existe para oferecer.
    """
    nome = nome or "Usuário"
    with st.sidebar, st.popover(
        nome.split()[0],
        icon=":material/account_circle:",
        width="stretch",
        type="tertiary",
    ):
        st.markdown(f"**{nome}**")
        papeis = ", ".join(papeis_da_sessao()) or "sem papel definido"
        st.caption(f"Papel: {papeis}")
        st.caption("Agente SDR Imobiliário v0.1")
        st.divider()
        authenticator.logout("Sair", "main", key="logout_menu")
