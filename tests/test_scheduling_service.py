"""Testes do SchedulingService: criação, validação e efeito no funil."""

from datetime import UTC, datetime, timedelta

import pytest

from src.services.lead_service import LeadService
from src.services.scheduling_service import SchedulingService


@pytest.fixture
def scheduling():
    return SchedulingService()


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="agenda-001", db=db
    ).id


@pytest.fixture
def amanha():
    return datetime.now(UTC) + timedelta(days=1)


def test_cria_agendamento_pendente(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    assert agendamento.id is not None
    assert agendamento.status == "pendente"


def test_agendar_move_o_lead_para_agendado(scheduling, lead_id, amanha, db):
    scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    assert LeadService().get_lead(lead_id, db).status == "agendado"


def test_tipo_invalido_e_rejeitado(scheduling, lead_id, amanha, db):
    with pytest.raises(ValueError):
        scheduling.create(lead_id=lead_id, tipo="cafe_da_manha", data_hora=amanha, db=db)


def test_observacoes_sao_persistidas(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="reuniao", data_hora=amanha,
        observacoes="Lead prefere o periodo da tarde", db=db,
    )
    assert agendamento.observacoes == "Lead prefere o periodo da tarde"


def test_lista_por_lead(scheduling, lead_id, amanha, db):
    scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    scheduling.create(lead_id=lead_id, tipo="reuniao", data_hora=amanha + timedelta(days=1), db=db)
    assert len(scheduling.list_by_lead(lead_id, db)) == 2


def test_atualiza_status(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    atualizado = scheduling.update_status(agendamento.id, "confirmado", db)
    assert atualizado.status == "confirmado"


def test_status_invalido_e_rejeitado(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    with pytest.raises(ValueError):
        scheduling.update_status(agendamento.id, "talvez", db)


def test_conta_pendentes(scheduling, lead_id, amanha, db):
    assert scheduling.get_pending_count(db) == 0
    scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)
    assert scheduling.get_pending_count(db) == 1
