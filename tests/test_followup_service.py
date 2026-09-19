"""Testes do FollowUpService: elegibilidade, réguas e idempotência."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from src.db.models import Agendamento
from src.services.followup_service import REGUAS, FollowUpService
from src.services.lead_service import LeadService


@pytest.fixture
def followup():
    return FollowUpService()


@pytest.fixture
def lead_service():
    return LeadService()


def criar_lead(lead_service, db, status, sufixo="1"):
    lead = lead_service.get_or_create_lead(
        channel="teste", external_id=f"fup-{sufixo}", db=db, nome="Ana"
    )
    lead.status = status
    db.commit()
    return lead.id


def envelhecer(db, lead_id, horas):
    """Recua no tempo o lead e suas mensagens, simulando inatividade."""
    db.execute(
        text("UPDATE mensagens SET timestamp = timestamp - make_interval(hours => :h) "
             "WHERE lead_id = :l"),
        {"h": horas, "l": lead_id},
    )
    db.execute(
        text("UPDATE leads SET created_at = created_at - make_interval(hours => :h) "
             "WHERE id = :l"),
        {"h": horas, "l": lead_id},
    )
    db.commit()


# --- Elegibilidade -----------------------------------------------------------


def test_lead_recem_criado_nao_e_elegivel(followup, lead_service, db):
    criar_lead(lead_service, db, "novo")
    assert followup.get_eligible_leads(db) == []


def test_lead_novo_calado_entra_na_regua_correspondente(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "novo")
    envelhecer(db, lead_id, 3)  # regua exige 2h

    elegiveis = followup.get_eligible_leads(db)
    assert [(lead.id, r) for lead, r in elegiveis] == [(lead_id, "lead_novo_sem_resposta")]


def test_silencio_insuficiente_nao_gera_followup(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="qual sua urgencia?", message_type="chat", db=db,
    )
    envelhecer(db, lead_id, 2)  # regua exige 6h
    assert followup.get_eligible_leads(db) == []


def test_lead_que_respondeu_por_ultimo_nao_recebe_followup(followup, lead_service, db):
    """Se a última mensagem é do lead, o que falta é resposta, não follow-up."""
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="qual sua urgencia?", message_type="chat", db=db,
    )
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="user",
        content="e alta", message_type="chat", db=db,
    )
    envelhecer(db, lead_id, 48)
    assert followup.get_eligible_leads(db) == []


def test_regua_e_escolhida_pelo_status_do_lead(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "qualificado")
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="separei estas opcoes", message_type="chat", db=db,
    )
    envelhecer(db, lead_id, 30)  # regua exige 24h

    elegiveis = followup.get_eligible_leads(db)
    assert [r for _, r in elegiveis] == ["pos_envio_imoveis"]


def test_lead_recebe_no_maximo_uma_regua_por_ciclo(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    envelhecer(db, lead_id, 100)
    elegiveis = followup.get_eligible_leads(db)
    assert len([lead for lead, _ in elegiveis if lead.id == lead_id]) == 1


def test_limite_de_tentativas_bloqueia_novos_followups(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    envelhecer(db, lead_id, 48)

    maximo = REGUAS["qualificacao_interrompida"]["max_tentativas"]
    for _ in range(maximo):
        followup.record_attempt(
            lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
        )

    assert followup.get_eligible_leads(db) == []


# --- Régua pós-agendamento ---------------------------------------------------


def test_visita_proxima_entra_na_regua_pos_agendamento(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "agendado")
    db.add(Agendamento(
        lead_id=lead_id, tipo="visita", status="confirmado",
        data_hora=datetime.now(UTC) + timedelta(hours=12),
    ))
    db.commit()

    elegiveis = followup.get_eligible_leads(db)
    assert [(lead.id, r) for lead, r in elegiveis] == [(lead_id, "pos_agendamento")]


def test_visita_distante_ainda_nao_gera_lembrete(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "agendado")
    db.add(Agendamento(
        lead_id=lead_id, tipo="visita", status="confirmado",
        data_hora=datetime.now(UTC) + timedelta(days=5),
    ))
    db.commit()
    assert followup.get_eligible_leads(db) == []


def test_visita_no_passado_nao_gera_lembrete(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "agendado")
    db.add(Agendamento(
        lead_id=lead_id, tipo="visita", status="confirmado",
        data_hora=datetime.now(UTC) - timedelta(hours=2),
    ))
    db.commit()
    assert followup.get_eligible_leads(db) == []


def test_agendamento_cancelado_nao_gera_lembrete(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "agendado")
    db.add(Agendamento(
        lead_id=lead_id, tipo="visita", status="cancelado",
        data_hora=datetime.now(UTC) + timedelta(hours=12),
    ))
    db.commit()
    assert followup.get_eligible_leads(db) == []


# --- Tentativas e idempotência ----------------------------------------------


def test_tentativas_sao_numeradas_em_sequencia(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    numeros = [
        followup.record_attempt(
            lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
        ).attempt_number
        for _ in range(3)
    ]
    assert numeros == [1, 2, 3]


def test_tentativa_duplicada_e_bloqueada_pelo_banco(followup, lead_service, db, monkeypatch):
    """Duas execuções concorrentes calculam o mesmo número; a segunda não passa."""
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    followup.record_attempt(
        lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
    )

    # simula a corrida: a segunda execução ainda enxerga a contagem anterior
    monkeypatch.setattr(followup, "get_attempts_count", lambda lead, regua, sessao: 0)
    duplicada = followup.record_attempt(
        lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
    )

    assert duplicada is None


def test_contagem_e_por_regua(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    followup.record_attempt(
        lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
    )
    assert followup.get_attempts_count(lead_id, "qualificacao_interrompida", db) == 1
    assert followup.get_attempts_count(lead_id, "pos_envio_imoveis", db) == 0


# --- Inativação --------------------------------------------------------------


def test_regua_de_silencio_esgotada_marca_inativo(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    for _ in range(REGUAS["qualificacao_interrompida"]["max_tentativas"]):
        followup.record_attempt(
            lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
        )
    assert followup.deve_marcar_inativo(lead_id, "qualificacao_interrompida", db)


def test_pos_agendamento_nunca_inativa_o_lead(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "agendado")
    for _ in range(REGUAS["pos_agendamento"]["max_tentativas"]):
        followup.record_attempt(
            lead_id=lead_id, regua="pos_agendamento", status="sent", db=db
        )
    assert not followup.deve_marcar_inativo(lead_id, "pos_agendamento", db)


def test_regua_com_tentativas_restantes_nao_inativa(followup, lead_service, db):
    lead_id = criar_lead(lead_service, db, "em_qualificacao")
    followup.record_attempt(
        lead_id=lead_id, regua="qualificacao_interrompida", status="sent", db=db
    )
    assert not followup.deve_marcar_inativo(lead_id, "qualificacao_interrompida", db)
