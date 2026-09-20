"""Quem enxerga qual menu.

O papel vem do `roles:` de `config/credentials.yaml`, que o
streamlit-authenticator publica na sessão. `menu_do_papel` é a única regra de
visibilidade da aplicação, e fica fora do Streamlit justamente para caber num
teste.
"""

import pytest
import yaml

from src.ui.papeis import PAPEL_ADMIN, PAPEL_CORRETOR, e_admin, menu_do_papel

DASHBOARD, LEADS, CHAT, AJUDA = "dashboard", "leads", "chat", "ajuda"
FICHA = "ficha"


def _menu(papeis):
    """Só os itens de menu: a ficha entra separada, escondida."""
    return menu_do_papel(DASHBOARD, LEADS, CHAT, AJUDA, papeis)


def test_admin_ve_o_simulador():
    assert _menu([PAPEL_ADMIN]) == [DASHBOARD, LEADS, CHAT, AJUDA]


def test_corretor_nao_ve_o_simulador():
    """O simulador é ferramenta de teste, não de atendimento."""
    assert _menu([PAPEL_CORRETOR]) == [DASHBOARD, LEADS, AJUDA]


@pytest.mark.parametrize("papeis", [None, [], ["desconhecido"]])
def test_sem_papel_reconhecido_cai_no_menu_menor(papeis):
    """Ausência de papel não promove ninguém."""
    assert _menu(papeis) == [DASHBOARD, LEADS, AJUDA]
    assert not e_admin(papeis)


def test_dashboard_e_sempre_a_primeira_pagina():
    """A primeira da lista é a que responde por `default=True`."""
    for papeis in ([PAPEL_ADMIN], [PAPEL_CORRETOR], None):
        assert _menu(papeis)[0] == DASHBOARD


def test_papel_extra_junto_do_admin_continua_valendo():
    assert _menu([PAPEL_CORRETOR, PAPEL_ADMIN]) == [DASHBOARD, LEADS, CHAT, AJUDA]


def test_ajuda_aparece_para_todo_papel():
    """Quem mais precisa dela é justamente quem tem menos acesso."""
    for papeis in ([PAPEL_ADMIN], [PAPEL_CORRETOR], None):
        assert _menu(papeis)[-1] == AJUDA


def test_credenciais_versionadas_declaram_os_papeis():
    """Sem `roles:` no YAML todo mundo cairia no menu do corretor."""
    with open("config/credentials.yaml", encoding="utf-8") as arquivo:
        config = yaml.safe_load(arquivo)

    usuarios = config["credentials"]["usernames"]
    assert usuarios["admin"]["roles"] == [PAPEL_ADMIN]
    assert usuarios["corretor1"]["roles"] == [PAPEL_CORRETOR]


def test_ficha_vai_junto_mas_no_fim_da_lista():
    """Ela precisa estar registrada para ter URL, e `visibility="hidden"` em
    `app.py` é o que a mantém fora do menu."""
    paginas = menu_do_papel(DASHBOARD, LEADS, CHAT, AJUDA, [PAPEL_ADMIN], FICHA)

    assert paginas == [DASHBOARD, LEADS, CHAT, AJUDA, FICHA]


def test_sem_ficha_o_menu_nao_ganha_item_vazio():
    assert FICHA not in menu_do_papel(DASHBOARD, LEADS, CHAT, AJUDA, [PAPEL_ADMIN])
