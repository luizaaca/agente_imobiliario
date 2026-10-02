"""Despacho dos follow-ups que foram gerados sem remetente.

O botão do painel e o script de ciclo avulso geram a mensagem sem ter como
enviá-la; quem envia é o processo do Telegram, que olha as pendentes a cada
poucos segundos. Ele só pode mandar o que ainda faz sentido mandar.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.agent import followup_agent as followup_agent_mod
from src.db.models import FollowUpAttempt, Mensagem
from src.scheduler import followup_runner
from src.scheduler.followup_runner import (
    VALIDADE_DO_PENDENTE,
    dispatch_pending_followups,
    run_followup_para_lead,
)
from src.services.lead_service import LeadService


class Remetente:
    """Sender de mentira, que anota o que mandaria."""

    def __init__(self, erro: Exception | None = None):
        self.enviados: list[tuple[str, str, str]] = []
        self.erro = erro

    async def __call__(self, canal, chat_id, texto):
        if self.erro:
            raise self.erro
        self.enviados.append((canal, chat_id, texto))
        return True


def _lead(db, canal="telegram", externo="900200"):
    lead = LeadService().get_or_create_lead(
        channel=canal, external_id=externo, db=db, nome="Rita"
    )
    LeadService().update_status(lead.id, "em_qualificacao", db)
    return lead.id


def _gerar(lead_id, llm_fake, texto="Rita, ainda procurando?", sender=None):
    """Gera como o botão do painel gera: sem remetente, ou com um."""
    with followup_agent_mod.followup_agent.override(model=llm_fake(texto)):
        asyncio.run(run_followup_para_lead(lead_id, sender=sender))


def _despachar(sender):
    return asyncio.run(dispatch_pending_followups(sender=sender))


def _tentativas(db, lead_id):
    db.expire_all()
    return (
        db.query(FollowUpAttempt)
        .filter(FollowUpAttempt.lead_id == lead_id)
        .order_by(FollowUpAttempt.attempt_number)
        .all()
    )


def test_envia_o_que_o_painel_gerou(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    remetente = Remetente()

    stats = _despachar(remetente)

    assert remetente.enviados == [("telegram", "900200", "Rita, ainda procurando?")]
    assert stats["enviados"] == 1
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "sent"
    mensagem = db.query(Mensagem).filter(Mensagem.id == tentativa.message_id).one()
    assert mensagem.status == "sent" and mensagem.sent_at is not None


def test_mensagem_de_canal_sem_envio_fica_como_esta(db, llm_fake):
    """No Streamlit, `generated` já é o fim: a mensagem está no chat do lead."""
    lead_id = _lead(db, canal="streamlit", externo="sessao-1")
    _gerar(lead_id, llm_fake)
    remetente = Remetente()

    _despachar(remetente)

    assert remetente.enviados == []
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "generated"


def test_mensagem_velha_nao_sai(db, llm_fake):
    """O bot subindo não pode despejar o que foi gerado há dias."""
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    [tentativa] = _tentativas(db, lead_id)
    tentativa.created_at = datetime.now(UTC) - VALIDADE_DO_PENDENTE - timedelta(minutes=1)
    db.commit()
    remetente = Remetente()

    stats = _despachar(remetente)

    assert remetente.enviados == []
    assert stats["descartados"] == 1
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "skipped"
    assert "expirou" in tentativa.failure_reason


def test_mensagem_dentro_da_validade_sai(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    [tentativa] = _tentativas(db, lead_id)
    tentativa.created_at = datetime.now(UTC) - VALIDADE_DO_PENDENTE + timedelta(minutes=1)
    db.commit()
    remetente = Remetente()

    _despachar(remetente)

    assert len(remetente.enviados) == 1


def test_quem_respondeu_nao_recebe_o_follow_up(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    LeadService().save_message(
        lead_id=lead_id, channel="telegram", role="user", content="Oi, voltei",
        message_type="chat", db=db,
    )
    remetente = Remetente()

    _despachar(remetente)

    assert remetente.enviados == []
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "skipped"
    assert "respondeu" in tentativa.failure_reason


def test_com_duas_pendentes_so_a_ultima_sai(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake, texto="primeira")
    _gerar(lead_id, llm_fake, texto="segunda")
    remetente = Remetente()

    _despachar(remetente)

    assert [texto for _, _, texto in remetente.enviados] == ["segunda"]
    primeira, segunda = _tentativas(db, lead_id)
    assert (primeira.status, segunda.status) == ("skipped", "sent")
    assert "mais recente" in primeira.failure_reason


def test_falha_no_envio_fica_registrada(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)

    stats = _despachar(Remetente(erro=TimeoutError("sem rede")))

    assert stats["falhas"] == 1
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "failed"
    assert "TimeoutError" in tentativa.failure_reason
    mensagem = db.query(Mensagem).filter(Mensagem.id == tentativa.message_id).one()
    assert mensagem.status == "generated"


def test_rodar_de_novo_nao_manda_de_novo(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    remetente = Remetente()

    _despachar(remetente)
    _despachar(remetente)

    assert len(remetente.enviados) == 1


def test_quem_nao_reserva_nao_envia(db, llm_fake, monkeypatch):
    """Duas execuções que leram a mesma pendente: só uma a envia.

    A triagem é congelada para as duas devolverem a mesma lista, como se
    tivessem lido o banco no mesmo instante; quem decide é a reserva.
    """
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)
    lida = followup_runner._triar_pendentes(
        {"enviados": 0, "falhas": 0, "descartados": 0}
    )
    monkeypatch.setattr(followup_runner, "_triar_pendentes", lambda stats: list(lida))
    remetente = Remetente()

    _despachar(remetente)
    _despachar(remetente)

    assert len(remetente.enviados) == 1


def test_sem_remetente_nao_mexe_em_nada(db, llm_fake):
    lead_id = _lead(db)
    _gerar(lead_id, llm_fake)

    _despachar(None)

    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == "generated"


# --- O ciclo, com remetente, diante de um canal sem envio --------------------


@pytest.mark.parametrize(
    ("canal", "externo", "status", "chamou"),
    [
        ("streamlit", "sessao-2", "generated", False),
        ("telegram", "900300", "sent", True),
    ],
)
def test_ciclo_so_pede_envio_a_canal_que_tem(db, llm_fake, canal, externo, status, chamou):
    """Antes, lead do Streamlit com o bot no ar virava `failed`.

    O remetente recusava por não ser Telegram, e a recusa entrava como falha:
    a taxa de falha de follow-up chegava a 100% sem nada ter falhado.
    """
    lead_id = _lead(db, canal=canal, externo=externo)
    remetente = Remetente()

    _gerar(lead_id, llm_fake, sender=remetente)

    assert bool(remetente.enviados) is chamou
    [tentativa] = _tentativas(db, lead_id)
    assert tentativa.status == status
    assert tentativa.failure_reason is None
