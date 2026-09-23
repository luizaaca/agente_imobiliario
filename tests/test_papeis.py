"""Quem enxerga qual menu.

O papel vem do `roles:` de `config/credentials.yaml`, que o
streamlit-authenticator publica na sessão. `menu_do_papel` é a única regra de
visibilidade da aplicação, e fica fora do Streamlit justamente para caber num
teste.
"""

import pytest
import yaml

from src.ui.papeis import (
    PAPEL_ADMIN,
    PAPEL_CORRETOR,
    e_admin,
    menu_do_papel,
    ve_os_bastidores,
)

DASHBOARD, LEADS, CHAT, AJUDA = "dashboard", "leads", "chat", "ajuda"
FICHA = "ficha"


def _menu(papeis):
    """Todas as páginas, na ordem em que aparecem no menu.

    A ficha entra separada, escondida, e por isso fica de fora daqui.
    """
    secoes = menu_do_papel(DASHBOARD, LEADS, CHAT, AJUDA, papeis)
    return [pagina for paginas in secoes.values() for pagina in paginas]


def _secoes(papeis, ficha=None):
    return menu_do_papel(DASHBOARD, LEADS, CHAT, AJUDA, papeis, ficha)


def test_admin_ve_o_simulador():
    assert _menu([PAPEL_ADMIN]) == [DASHBOARD, LEADS, AJUDA, CHAT]


def test_corretor_nao_ve_o_simulador():
    """O simulador é ferramenta de teste, não de atendimento."""
    assert _menu([PAPEL_CORRETOR]) == [DASHBOARD, LEADS, AJUDA]


@pytest.mark.parametrize("papeis", [None, [], ["desconhecido"]])
def test_sem_papel_reconhecido_cai_no_menu_menor(papeis):
    """Ausência de papel não promove ninguém."""
    assert _menu(papeis) == [DASHBOARD, LEADS, AJUDA]
    assert not e_admin(papeis)


def test_so_o_admin_ve_os_bastidores_da_conversa():
    """Custo em dólar e SQL do agente são de quem opera, não de quem atende."""
    assert ve_os_bastidores([PAPEL_ADMIN])
    assert not ve_os_bastidores([PAPEL_CORRETOR])
    for papeis in (None, [], ["desconhecido"]):
        assert not ve_os_bastidores(papeis)


def test_dashboard_e_sempre_a_primeira_pagina():
    """A primeira da lista é a que responde por `default=True`."""
    for papeis in ([PAPEL_ADMIN], [PAPEL_CORRETOR], None):
        assert _menu(papeis)[0] == DASHBOARD


def test_papel_extra_junto_do_admin_continua_valendo():
    assert _menu([PAPEL_CORRETOR, PAPEL_ADMIN]) == [DASHBOARD, LEADS, AJUDA, CHAT]


def test_ajuda_aparece_para_todo_papel():
    """Quem mais precisa dela é justamente quem tem menos acesso."""
    for papeis in ([PAPEL_ADMIN], [PAPEL_CORRETOR], None):
        assert AJUDA in _menu(papeis)


def test_simulador_fica_depois_da_ajuda():
    """A ordem do menu: trabalho, ajuda, e o simulador por último."""
    menu = _menu([PAPEL_ADMIN])
    assert menu[-1] == CHAT
    assert menu[-2] == AJUDA


def test_sem_o_simulador_a_ajuda_e_a_ultima():
    for papeis in ([PAPEL_CORRETOR], None):
        assert _menu(papeis)[-1] == AJUDA


def test_credenciais_versionadas_declaram_os_papeis():
    """Sem `roles:` no YAML todo mundo cairia no menu do corretor."""
    with open("config/credentials.yaml", encoding="utf-8") as arquivo:
        config = yaml.safe_load(arquivo)

    usuarios = config["credentials"]["usernames"]
    assert usuarios["admin"]["roles"] == [PAPEL_ADMIN]
    assert usuarios["corretor1"]["roles"] == [PAPEL_CORRETOR]


def test_ficha_vai_junto_mas_no_fim():
    """Ela precisa estar registrada para ter URL, e `visibility="hidden"` em
    `app.py` é o que a mantém fora do menu."""
    assert _secoes([PAPEL_ADMIN], FICHA)[""][-1] == FICHA


def test_sem_ficha_o_menu_nao_ganha_item_vazio():
    assert FICHA not in _menu([PAPEL_ADMIN])


def test_menu_tem_uma_secao_so():
    """Chave nomeada no `st.navigation` vira cabeçalho recolhível, não risco.

    Os separadores finos antes da ajuda e do simulador são CSS, em
    `ui.estilo`, escolhidos pelo `href` de cada link.
    """
    assert list(_secoes([PAPEL_ADMIN], FICHA)) == [""]
