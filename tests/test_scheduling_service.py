"""Testes do SchedulingService: criação, validação e efeito no funil."""

from datetime import UTC, datetime, timedelta

import pytest

from src.db.models import Lead
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


# --- Vinculo com o imovel ----------------------------------------------------
#
# A tool `agendar_reuniao` recebe `imovel_id` do modelo e o persiste; sem a
# coluna o dado seria descartado em silencio.


def test_agendamento_guarda_o_imovel(scheduling, lead_id, amanha, catalogo, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, imovel_id=3, db=db
    )

    assert agendamento.imovel_id == 3
    assert agendamento.imovel.titulo == "Cobertura Moema Alto Padrao"


def test_agendamento_sem_imovel_continua_valido(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="reuniao", data_hora=amanha, db=db
    )

    assert agendamento.imovel_id is None
    assert agendamento.imovel is None


# --- Edição pela ficha -------------------------------------------------------


def test_editar_reescreve_data_tipo_e_status(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    depois = amanha + timedelta(days=3)

    scheduling.editar(
        agendamento.id, db, tipo="reuniao", data_hora=depois, status="confirmado"
    )

    atual = scheduling.get(agendamento.id, db)
    assert (atual.tipo, atual.status) == ("reuniao", "confirmado")
    assert atual.data_hora.date() == depois.date()


def test_editar_apaga_o_que_o_corretor_deixou_em_branco(
    scheduling, lead_id, amanha, catalogo, db
):
    """`None` aqui é "o corretor apagou", não "não foi informado".

    É o mesmo critério da edição de lead: o caminho manual precisa conseguir
    limpar o que veio errado da conversa.
    """
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db,
        observacoes="levar a planta", imovel_id=3,
    )

    scheduling.editar(
        agendamento.id, db, tipo="visita", data_hora=amanha, status="pendente",
        observacoes=None, imovel_id=None,
    )

    atual = scheduling.get(agendamento.id, db)
    assert atual.observacoes is None
    assert atual.imovel_id is None


def test_editar_nao_mexe_no_status_do_lead(scheduling, lead_id, amanha, db):
    """Cancelar uma visita não devolve o lead ao funil sozinho.

    Só quem está atendendo sabe se a oportunidade morreu ou vai ser remarcada.
    """
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    assert db.query(Lead).filter(Lead.id == lead_id).one().status == "agendado"

    scheduling.editar(
        agendamento.id, db, tipo="visita", data_hora=amanha, status="cancelado"
    )

    assert db.query(Lead).filter(Lead.id == lead_id).one().status == "agendado"


def test_editar_rejeita_tipo_invalido(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    with pytest.raises(ValueError):
        scheduling.editar(
            agendamento.id, db, tipo="churrasco", data_hora=amanha, status="pendente"
        )


def test_editar_rejeita_status_invalido(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    with pytest.raises(ValueError):
        scheduling.editar(
            agendamento.id, db, tipo="visita", data_hora=amanha, status="talvez"
        )


def test_editar_agendamento_inexistente_devolve_none(scheduling, amanha, db):
    assert scheduling.editar(
        999999, db, tipo="visita", data_hora=amanha, status="pendente"
    ) is None


def test_excluir_apaga_o_agendamento(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    assert scheduling.excluir(agendamento.id, db) is True
    assert scheduling.get(agendamento.id, db) is None
    assert scheduling.list_by_lead(lead_id, db) == []


def test_excluir_nao_devolve_o_lead_ao_funil(scheduling, lead_id, amanha, db):
    """O lead pode ter outros compromissos, e regredir no funil é decisão de
    quem está atendendo — não efeito colateral de apagar uma linha."""
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    scheduling.excluir(agendamento.id, db)

    assert db.query(Lead).filter(Lead.id == lead_id).one().status == "agendado"


def test_excluir_agendamento_inexistente_devolve_false(scheduling, db):
    assert scheduling.excluir(999999, db) is False
