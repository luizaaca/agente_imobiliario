"""Tela de login: a primeira coisa que se ve da aplicacao.

Vive separada de `app.py` porque tem um problema proprio — e a unica tela sem
navegacao, sem barra lateral e sem conteudo para ocupar a largura da pagina.
O resto da aplicacao roda em `layout="wide"`, que aqui deixaria dois campos de
formulario com mais de mil pixels de largura.
"""

from typing import Any, Optional

import streamlit as st

# Largura da caixa de login. Estreita o bastante para os campos terem tamanho
# de campo, e nao de faixa atravessando a tela.
_LARGURA = 420

_CSS = f"""
<style>
/* A barra lateral e da navegacao, e aqui nao ha para onde navegar. Quem
   deixou a barra aberta na sessao anterior veria um painel vazio ao lado do
   login; escondemos os dois controles dela enquanto ninguem entrou. */
section[data-testid="stSidebar"],
[data-testid="stExpandSidebarButton"] {{
  display: none !important;
}}

/* A caixa centralizada no lugar da largura cheia da pagina. */
.st-key-caixa_de_login {{
  max-width: {_LARGURA}px;
  margin-inline: auto;
  /* Um respiro no topo: colada na borda a caixa parece cortada. */
  margin-top: 4vh;
}}
/* O formulario do streamlit-authenticator ja desenha a propria borda; a
   segunda borda em volta viraria caixa dentro de caixa. */
.st-key-caixa_de_login [data-testid="stForm"] {{
  border: none !important;
  padding: 0 !important;
}}
</style>
"""

# O restante da aplicacao esta em portugues; sem isto o formulario abre em
# ingles, que e o padrao da biblioteca.
CAMPOS = {
    "Form name": "Entrar",
    "Username": "Usuário",
    "Password": "Senha",
    "Login": "Entrar",
}


def tela_de_login(authenticator: Any) -> Optional[bool]:
    """Desenha o login e devolve o status da autenticacao.

    `None` significa que ainda nao houve tentativa, `False` que as credenciais
    nao conferem e `True` que entrou — os mesmos valores que o
    streamlit-authenticator publica em `st.session_state`.
    """
    # `location="unrendered"` valida o cookie sem desenhar nada. Precisa vir
    # antes: quem chega com sessao valida nao passa pela tela de login, e sem
    # esta checagem a marca e o CSS de login — inclusive o que esconde a barra
    # lateral — apareceriam por cima do dashboard no mesmo carregamento.
    authenticator.login(location="unrendered")
    if st.session_state.get("authentication_status") is True:
        return True

    st.markdown(_CSS, unsafe_allow_html=True)

    with st.container(key="caixa_de_login"):
        # Marca em tamanho de cabecalho, e nao de titulo: em 420px o titulo
        # quebrava em duas linhas e ficava maior que o formulario que o segue.
        st.markdown("### :material/real_estate_agent: Agente SDR Imobiliário")
        st.caption("Pré-vendas imobiliário com agente de IA · POC")

        authenticator.login(fields=CAMPOS)
        status = st.session_state.get("authentication_status")

        if status is False:
            st.error("Usuário ou senha incorretos.", icon=":material/lock:")
        elif status is None:
            st.info("Entre para acessar o sistema.", icon=":material/login:")

    return status
