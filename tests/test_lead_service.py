"""Testes do LeadService: score, funil e saneamento dos dados da LLM."""

from decimal import Decimal

import pytest

from src.db.models import Lead
from src.services.lead_service import LeadService

QUALIFICACAO_COMPLETA = {
    "intencao": "compra",
    "orcamento_max": 700000,
    "bairro_interesse": "Bela Vista",
    "quartos": 2,
}


@pytest.fixture
def lead_service():
    return LeadService()


@pytest.fixture
def lead_id(lead_service, db):
    return lead_service.get_or_create_lead(
        channel="teste", external_id="teste-001", db=db, nome="Ana"
    ).id


# --- Identidade de canal -----------------------------------------------------


def test_get_or_create_reaproveita_o_mesmo_external_id(lead_service, db):
    primeiro = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    segundo = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    assert primeiro.id == segundo.id


def test_external_ids_diferentes_geram_leads_diferentes(lead_service, db):
    a = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    b = lead_service.get_or_create_lead(channel="teste", external_id="x2", db=db)
    assert a.id != b.id


def test_busca_por_prefixo_nao_trata_underscore_como_curinga(lead_service, db):
    """'_' é curinga em LIKE; o prefixo de um usuário não pode casar com outro."""
    esperado = lead_service.get_or_create_lead(
        channel="streamlit", external_id="streamlit_ana_abc123", db=db
    )
    lead_service.get_or_create_lead(
        channel="streamlit", external_id="streamlitXanaYxyz789", db=db
    )

    achado = lead_service.get_latest_identity_by_prefix("streamlit", "streamlit_ana_", db)
    assert achado is not None
    assert achado.lead_id == esperado.id


# --- Funil -------------------------------------------------------------------


def test_lead_nasce_como_novo(lead_service, lead_id, db):
    assert lead_service.get_lead(lead_id, db).status == "novo"


def test_qualificacao_parcial_mantem_em_qualificacao(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    assert lead_service.get_lead(lead_id, db).status == "em_qualificacao"


def test_dados_minimos_completos_promovem_para_qualificado(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "qualificado"


def test_orcamento_min_tambem_satisfaz_o_grupo_de_orcamento(lead_service, lead_id, db):
    dados = dict(QUALIFICACAO_COMPLETA)
    dados.pop("orcamento_max")
    dados["orcamento_min"] = 300000
    lead_service.update_qualification(lead_id, dados, db)
    assert lead_service.get_lead(lead_id, db).status == "qualificado"


def test_status_agendado_nao_regride_com_nova_qualificacao(lead_service, lead_id, db):
    lead_service.update_status(lead_id, "agendado", db)
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "agendado"


def test_lead_inativo_nao_e_promovido_apenas_por_dados(lead_service, lead_id, db):
    lead_service.update_status(lead_id, "inativo", db)
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "inativo"


def test_mudanca_de_intencao_no_meio_da_conversa(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    lead_service.update_qualification(lead_id, {"intencao": "aluguel"}, db)
    assert lead_service.get_lead(lead_id, db).intencao == "aluguel"


# --- Saneamento dos dados vindos da LLM --------------------------------------


def test_valor_maior_que_a_coluna_e_truncado(lead_service):
    """Regressão: 95 caracteres em `perfil` (VARCHAR(30)) derrubavam o turno."""
    frase = "Busca de imovel para aluguel na zona leste, com interesse em 1 ou 2 quartos, a vista."
    limpo = lead_service.sanitizar_qualificacao({"perfil": frase})
    assert len(limpo["perfil"]) == 30


def test_persistir_texto_longo_nao_levanta_erro(lead_service, lead_id, db):
    frase = "x" * 400
    lead_service.update_qualification(lead_id, {"perfil": frase}, db)
    assert len(lead_service.get_lead(lead_id, db).perfil) == 30


def test_valor_fora_do_vocabulario_e_descartado(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"urgencia": "muito urgente mesmo"})
    assert "urgencia" not in limpo


def test_valor_do_vocabulario_e_normalizado_para_minusculo(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"intencao": "ALUGUEL"})
    assert limpo["intencao"] == "aluguel"


def test_valores_nao_textuais_passam_intactos(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"quartos": 3, "orcamento_max": 500000.0})
    assert limpo == {"quartos": 3, "orcamento_max": 500000.0}


# --- Score -------------------------------------------------------------------


def test_score_de_lead_sem_dados_e_zero(lead_service, lead_id, db):
    assert lead_service.calculate_score(lead_id, db) == Decimal("0.00")


def test_score_cresce_com_a_completude(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    parcial = lead_service.calculate_score(lead_id, db)

    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    completo = lead_service.calculate_score(lead_id, db)

    assert completo > parcial


def test_urgencia_alta_pontua_mais_que_baixa(lead_service, db):
    def score_para(urgencia, sufixo):
        lid = lead_service.get_or_create_lead(
            channel="teste", external_id=f"u-{sufixo}", db=db
        ).id
        lead_service.update_qualification(lid, {**QUALIFICACAO_COMPLETA, "urgencia": urgencia}, db)
        return lead_service.calculate_score(lid, db)

    assert score_para("alta", "alta") > score_para("baixa", "baixa")


def test_engajamento_do_lead_soma_ao_score(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    sem_mensagens = lead_service.calculate_score(lead_id, db)

    for i in range(6):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"mensagem {i}", message_type="chat", db=db,
        )
    com_mensagens = lead_service.calculate_score(lead_id, db)

    assert com_mensagens > sem_mensagens


def test_score_nunca_passa_de_dez(lead_service, lead_id, db):
    lead_service.update_qualification(
        lead_id,
        {**QUALIFICACAO_COMPLETA, "urgencia": "alta", "forma_pagamento": "a_vista",
         "tipologia_interesse": "apartamento"},
        db,
    )
    for i in range(15):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"m{i}", message_type="chat", db=db,
        )
    assert lead_service.calculate_score(lead_id, db) <= Decimal("10.00")


# --- Mensagens ---------------------------------------------------------------


def test_historico_volta_em_ordem_cronologica(lead_service, lead_id, db):
    for i in range(3):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"m{i}", message_type="chat", db=db,
        )
    conteudos = [m.content for m in lead_service.get_history(lead_id, 10, db)]
    assert conteudos == ["m0", "m1", "m2"]


def test_historico_respeita_o_limite_mantendo_as_mais_recentes(lead_service, lead_id, db):
    for i in range(5):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"m{i}", message_type="chat", db=db,
        )
    conteudos = [m.content for m in lead_service.get_history(lead_id, 2, db)]
    assert conteudos == ["m3", "m4"]


def test_has_message_type_identifica_handover(lead_service, lead_id, db):
    assert not lead_service.has_message_type(lead_id, "handover", db)
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="passando ao corretor", message_type="handover", db=db,
    )
    assert lead_service.has_message_type(lead_id, "handover", db)


def test_mark_message_sent_registra_o_envio(lead_service, lead_id, db):
    msg = lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant", content="oi",
        message_type="followup", db=db, status="generated",
    )
    lead_service.mark_message_sent(msg.id, db)
    db.refresh(msg)
    assert msg.status == "sent"
    assert msg.sent_at is not None


def test_dashboard_ordena_por_score_desc(lead_service, db):
    for sufixo, score in (("baixo", 2), ("alto", 9), ("medio", 5)):
        lid = lead_service.get_or_create_lead(
            channel="teste", external_id=f"d-{sufixo}", db=db
        ).id
        db.query(Lead).filter(Lead.id == lid).update({"score": score})
    db.commit()

    scores = [float(item.score) for item in lead_service.get_leads_for_dashboard({}, db)]
    assert scores == sorted(scores, reverse=True)
