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


def ve_os_bastidores(papeis: Optional[Sequence[str]]) -> bool:
    """Se este usuario enxerga o que a conversa custou e o que rodou por baixo.

    Custo em dolar do provider e SQL do agente de busca sao informacao de quem
    opera a aplicacao. Na ficha do corretor eles nao ajudam a atender ninguem
    e ainda afastam uma fala da seguinte.

    E o mesmo papel do simulador, e de proposito: admin e quem enxerga a
    maquina. Existe com nome proprio para a chamada na tela dizer o que esta
    em jogo — a regra e a visibilidade, nao o cargo.
    """
    return e_admin(papeis)


def papeis_da_sessao() -> list[str]:
    """Papeis do usuario logado, como o authenticator os deixou na sessao."""
    return list(st.session_state.get("roles") or [])


def menu_do_papel(
    dashboard: Any,
    leads: Any,
    chat: Any,
    ajuda: Any,
    papeis: Optional[Sequence[str]],
    ficha: Any = None,
) -> dict[str, list[Any]]:
    """Paginas entregues ao `st.navigation`, na ordem em que aparecem no menu.

    A ordem e: o trabalho do dia primeiro, a ajuda depois e o simulador por
    ultimo. O simulador so aparece para o admin — e ferramenta de teste, nao
    de atendimento —, e a ajuda aparece para todos, porque quem mais precisa
    dela e justamente quem tem menos acesso.

    A primeira da lista e a que responde por `default=True`, entao todo papel
    tem o dashboard como pagina inicial.

    A ficha do lead vai junto, no fim, mas e criada com
    `visibility="hidden"`: precisa estar registrada para ter URL e receber
    `st.switch_page`, e nao vira item de menu.

    Uma secao so, de titulo vazio. Uma chave nomeada do `st.navigation` nao
    desenha um risco: desenha um cabecalho com rotulo e seta de recolher, que
    transforma o item num grupo que se fecha. Os riscos finos antes da ajuda e
    do simulador sao CSS, em `ui.estilo`.
    """
    menu = [dashboard, leads, ajuda]
    if e_admin(papeis):
        menu.append(chat)
    if ficha is not None:
        menu.append(ficha)
    return {"": menu}
