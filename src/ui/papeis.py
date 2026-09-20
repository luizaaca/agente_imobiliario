"""Papel do usuario logado e o que ele enxerga.

O papel vem de `roles:` no `config/credentials.yaml`: o streamlit-authenticator
le o campo no login, publica em `st.session_state["roles"]` e o carrega no
cookie de sessao. Nada disso precisou ser construido aqui.

**Isto e separacao de telas, nao fronteira de seguranca.** O papel mora num
YAML que acompanha o repositorio; quem consegue edita-lo se da o papel que
quiser. Serve para nao poluir a tela do corretor com ferramenta de teste e
numero de custo, e nao para proteger dado sensivel de quem ja entrou. Uma
fronteira de verdade exigiria provedor de identidade e autorizacao por
operacao, o que o §9 dos criterios mantem fora do escopo da POC.
"""

from collections.abc import Sequence
from typing import Any, Optional

import streamlit as st

PAPEL_ADMIN = "admin"
PAPEL_CORRETOR = "corretor"


def e_admin(papeis: Optional[Sequence[str]]) -> bool:
    """Diz se a lista de papeis inclui `admin`.

    Ausencia de papel nao promove ninguem: um usuario sem `roles:` no YAML
    cai no menu do corretor, que e o conjunto menor.
    """
    return PAPEL_ADMIN in (papeis or [])


def papeis_da_sessao() -> list[str]:
    """Papeis do usuario logado, como o authenticator os deixou na sessao."""
    return list(st.session_state.get("roles") or [])


def menu_do_papel(
    dashboard: Any, leads: Any, chat: Any, papeis: Optional[Sequence[str]]
) -> list[Any]:
    """Paginas visiveis para estes papeis, na ordem do menu.

    O simulador de chat so aparece para o admin: e ferramenta de teste, nao
    de atendimento. A primeira da lista e a que responde por `default=True`,
    entao todo papel tem o dashboard como pagina inicial.
    """
    paginas = [dashboard, leads]
    if e_admin(papeis):
        paginas.append(chat)
    return paginas
