"""Disparo manual de follow-up, o botão do dashboard.

Mesma lógica do ciclo automático, gatilho diferente: dispensa a janela de
inatividade — o corretor, olhando o lead, já decidiu que é hora — e mantém o
teto de tentativas e o budget, que são limites de custo e de insistência.
"""

import asyncio

import pytest

from src.agent import followup_agent as followup_agent_mod
from src.db.models import FollowUpAttempt, Lead, Mensagem
from src.scheduler.followup_runner import run_followup_para_lead
from src.services.followup_service import REGUAS, FollowUpService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService


@pytest.fixture
def lead_em_qualificacao(db):
    lead = LeadService().get_or_create_lead(
        channel="telegram", external_id="900100", db=db, nome="Rita"
    )
    LeadService().update_status(lead.id, "em_qualificacao", db)
    return lead.id


def _disparar(lead_id, llm_fake, texto="Oi Rita, ainda procurando?", sender=None):
    with followup_agent_mod.followup_agent.override(model=llm_fake(texto)):
        return asyncio.run(run_followup_para_lead(lead_id, sender=sender))


def test_dispara_sem_esperar_a_janela_de_inatividade(lead_em_qualificacao, llm_fake, db):
    """O lead acabou de falar, então o ciclo automático não o pegaria."""
    assert FollowUpService().get_eligible_leads(db) == []

    resultado = _disparar(lead_em_qualificacao, llm_fake)

    assert resultado.executado
    assert resultado.stats["elegiveis"] == 1
    mensagem = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_em_qualificacao,
        Mensagem.message_type == "followup",
    ).one()
    assert "Rita" in mensagem.content


def test_registra_a_tentativa_na_regua_do_status(lead_em_qualificacao, llm_fake, db):
    _disparar(lead_em_qualificacao, llm_fake)

    tentativa = db.query(FollowUpAttempt).filter(
        FollowUpAttempt.lead_id == lead_em_qualificacao
    ).one()
    assert tentativa.regua == "qualificacao_interrompida"
    assert tentativa.attempt_number == 1


def test_envia_pelo_canal_quando_ha_remetente(lead_em_qualificacao, llm_fake, db):
    enviados = []

    async def sender(canal, chat_id, texto):
        enviados.append((canal, chat_id))
        return True

    resultado = _disparar(lead_em_qualificacao, llm_fake, sender=sender)

    assert resultado.stats["enviados"] == 1
    assert enviados == [("telegram", "900100")]


def test_teto_de_tentativas_continua_valendo(lead_em_qualificacao, llm_fake, db):
    """O limite da régua é de insistência, não de tempo: o botão não o burla."""
    servico = FollowUpService()
    maximo = REGUAS["qualificacao_interrompida"]["max_tentativas"]
    for _ in range(maximo):
        servico.record_attempt(
            lead_id=lead_em_qualificacao, regua="qualificacao_interrompida",
            status="sent", db=db,
        )

    resultado = _disparar(lead_em_qualificacao, llm_fake)

    assert not resultado.executado
    assert "esgotou" in resultado.motivo


def test_budget_estourado_impede_o_disparo(lead_em_qualificacao, llm_fake, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_daily_budget_exceeded", lambda self, db: True
    )

    resultado = _disparar(lead_em_qualificacao, llm_fake)

    assert not resultado.executado
    assert "diário" in resultado.motivo


def test_status_sem_regua_explica_em_vez_de_falhar(db, llm_fake):
    """`inativo` é o único status do funil sem régua.

    O lead chegou lá por ter esgotado as tentativas, então o botão precisa
    dizer isso ao corretor em vez de estourar uma exceção na tela.
    """
    lead = Lead(status="inativo")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    resultado = _disparar(lead.id, llm_fake)

    assert not resultado.executado
    assert "inativo" in resultado.motivo


def test_lead_inexistente_nao_explode(llm_fake):
    resultado = _disparar(999999, llm_fake)

    assert not resultado.executado
    assert "não encontrado" in resultado.motivo
