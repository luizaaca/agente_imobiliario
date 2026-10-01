"""O cartão de follow-ups do dashboard conta mensagens, não tentativas.

A tentativa existe também quando a geração falha: ela fica registrada sem
mensagem, para o teto da régua a enxergar. O cartão diz "mensagens geradas", e
uma falha não gerou nada.
"""

import pytest

from src.services.followup_service import FollowUpService
from src.services.lead_service import LeadService
from src.ui.dashboard import contar_followups


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="telegram", external_id="900400", db=db
    ).id


def _tentativa(db, lead_id, status, com_mensagem=True, regua="qualificacao_interrompida"):
    mensagem = None
    if com_mensagem:
        mensagem = LeadService().save_message(
            lead_id=lead_id, channel="telegram", role="assistant",
            content="Rita, ainda procurando?", message_type="followup", db=db,
            status="generated",
        ).id
    FollowUpService().record_attempt(
        lead_id=lead_id, regua=regua, status=status, db=db, message_id=mensagem,
        failure_reason=None if com_mensagem else "ValueError: LLM devolveu mensagem vazia",
    )


def test_geracao_que_falhou_nao_conta_como_mensagem(db, lead_id):
    _tentativa(db, lead_id, "failed", com_mensagem=False)

    assert contar_followups(db) == (0, 0)


def test_conta_o_que_gerou_mensagem_e_separa_o_que_saiu(db, lead_id):
    _tentativa(db, lead_id, "failed", com_mensagem=False)
    _tentativa(db, lead_id, "generated")
    _tentativa(db, lead_id, "sent")
    _tentativa(db, lead_id, "skipped")

    assert contar_followups(db) == (3, 1)


def test_envio_que_falhou_conta_como_gerada_e_nao_como_enviada(db, lead_id):
    """A mensagem existe e está na conversa; só não chegou ao canal."""
    _tentativa(db, lead_id, "failed", com_mensagem=True)

    assert contar_followups(db) == (1, 0)
