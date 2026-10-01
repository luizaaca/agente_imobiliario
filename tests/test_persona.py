"""Decisões de persona que o texto dos prompts precisa sustentar.

Não testam estilo, e sim regra: o que a Marina diz de si, o que ela sabe que
já tem, e o que o follow-up não pode prometer por não ter como cumprir.
"""

from types import SimpleNamespace

import pytest

from src.agent.followup_agent import build_followup_prompt
from src.agent.prompts import (
    FOLLOWUP_INSTRUCOES,
    FOLLOWUP_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from src.agent.sdr_agent import (
    ABERTURA_DA_CONVERSA,
    PEDIDO_DE_NOME,
    PEDIDO_DE_NOME_E_TELEFONE,
    PEDIDO_DE_TELEFONE,
    SEM_PEDIDO_DE_CONTATO,
    abertura_da_conversa,
    ficha_para_a_busca,
    montar_contexto_do_lead,
)
from src.services.lead_service import LeadService


def _lead(**campos):
    base = dict(
        nome="Rita", telefone=None, intencao=None, tipologia_interesse=None,
        orcamento_min=None, orcamento_max=None, bairro_interesse=None,
        regiao_interesse=None, quartos=None, urgencia=None, forma_pagamento=None,
        motivo_busca=None, amenidades_desejadas=None, status="novo",
    )
    return SimpleNamespace(**{**base, **campos})


def _lead_gravado(db, telefone=None):
    servico = LeadService()
    lead = servico.get_or_create_lead(channel="telegram", external_id="900900", db=db)
    if telefone:
        servico.update_qualification(lead.id, {"telefone": telefone}, db)
    return servico.get_lead(lead.id, db)


def test_contexto_diz_que_o_telefone_ja_veio_sem_mostrar_o_numero(db):
    """Pedido cedo, o telefone seria pedido de novo se o modelo não soubesse."""
    contexto = montar_contexto_do_lead(_lead_gravado(db, telefone="11987654321"))

    assert "Telefone: já informado" in contexto
    assert "987654321" not in contexto


def test_sem_telefone_o_contexto_nao_inventa_que_ele_existe(db):
    assert "Telefone" not in montar_contexto_do_lead(_lead_gravado(db))


def test_telefone_nao_vai_para_o_agente_de_busca():
    assert "Telefone" not in ficha_para_a_busca(_lead(telefone="11987654321"))


def test_marina_nao_se_anuncia_como_assistente_virtual_mas_nao_mente():
    apresentacao = SYSTEM_PROMPT.split("## 1. Descobrir a pessoa")[1].split("\n\n")[1]

    assert "assistente virtual" not in apresentacao
    assert "Se ela perguntar se está falando com uma pessoa, diga a verdade" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    "convite",
    ["Luiz", "Separei", "achei uma coisa", "sobre o mercado", "algo do mercado",
     "friozinho"],
)
def test_follow_up_nao_convida_a_inventar(convite):
    """O agente de follow-up não busca imóveis: não tem o que separar nem achar."""
    textos = [FOLLOWUP_SYSTEM_PROMPT, *FOLLOWUP_INSTRUCOES.values()]
    textos += [build_followup_prompt({}, "qualificacao_interrompida", n) for n in (1, 2, 3)]

    assert not any(convite in texto for texto in textos)


def test_abertura_nao_manda_se_anunciar_como_assistente_virtual():
    """A regra do prompt perdia para esta: é a última coisa que o modelo lê."""
    assert "você é a assistente virtual" not in ABERTURA_DA_CONVERSA
    assert "Não diga que é assistente virtual" in ABERTURA_DA_CONVERSA


@pytest.mark.parametrize(
    ("contato", "pedido"),
    [
        ({"nome": None}, PEDIDO_DE_NOME_E_TELEFONE),
        ({}, PEDIDO_DE_TELEFONE),
        ({"nome": None, "telefone": "(11) 98765-4321"}, PEDIDO_DE_NOME),
    ],
)
def test_abertura_pede_so_o_contato_que_falta(contato, pedido):
    """No Telegram o nome vem do perfil: pedir de novo soaria formulário."""
    abertura = abertura_da_conversa(_lead(**contato))

    assert abertura.startswith(ABERTURA_DA_CONVERSA)
    assert pedido in abertura
    assert "não pergunte o que ela procura" in abertura
    outros = {PEDIDO_DE_NOME_E_TELEFONE, PEDIDO_DE_TELEFONE, PEDIDO_DE_NOME} - {pedido}
    assert not any(o in abertura for o in outros)


def test_com_nome_e_telefone_a_abertura_vai_direto_a_pergunta():
    abertura = abertura_da_conversa(_lead(telefone="(11) 98765-4321"))

    assert abertura == ABERTURA_DA_CONVERSA + SEM_PEDIDO_DE_CONTATO


def test_sem_lead_a_abertura_pede_os_dois():
    assert PEDIDO_DE_NOME_E_TELEFONE in abertura_da_conversa(None)
