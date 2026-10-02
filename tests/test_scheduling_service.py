"""Testes do SchedulingService: criação, validação e efeito no funil."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.db.models import Agendamento, Lead
from src.services.lead_service import LeadService
from src.services.scheduling_service import (
    CompromissoJaMarcado,
    SchedulingService,
)


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
    """Traz o histórico, e não só o que está de pé."""
    primeiro = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    scheduling.update_status(primeiro.id, "cancelado", db)
    scheduling.create(
        lead_id=lead_id, tipo="reuniao", data_hora=amanha + timedelta(days=1), db=db
    )
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


# --- Um compromisso de pe por lead -------------------------------------------
#
# A regra morava so no codigo e nao se sustentou: um lead chegou a ter duas
# visitas pendentes ao mesmo tempo, marcadas em turnos diferentes, porque o
# modelo nao acertou o `agendamento_id` na hora de remarcar. Agora ha indice
# unico parcial, e o servico traduz a recusa em algo que a tela e o modelo
# conseguem ler.


def test_segundo_compromisso_em_outro_horario_e_recusado(
    scheduling, lead_id, amanha, db
):
    scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)

    with pytest.raises(CompromissoJaMarcado):
        scheduling.create(
            lead_id=lead_id, tipo="visita",
            data_hora=amanha + timedelta(days=2), db=db,
        )


def test_a_recusa_carrega_o_compromisso_que_ja_existe(
    scheduling, lead_id, amanha, db
):
    """Quem trata a recusa precisa dizer qual é — ao modelo e ao corretor."""
    existente = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    with pytest.raises(CompromissoJaMarcado) as conflito:
        scheduling.create(
            lead_id=lead_id, tipo="reuniao",
            data_hora=amanha + timedelta(days=2), db=db,
        )

    assert conflito.value.existente.id == existente.id


def test_pedir_o_mesmo_horario_de_novo_devolve_o_que_existe(
    scheduling, lead_id, amanha, db
):
    """Duplo clique na tela e retentativa do modelo não são remarcação."""
    primeiro = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    segundo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    assert segundo.id == primeiro.id
    assert len(scheduling.list_by_lead(lead_id, db)) == 1


def test_remarcar_cancela_o_antigo_e_cria_o_novo(scheduling, lead_id, amanha, db):
    """Cancelar e criar, e não mover a linha: a data trocada é informação."""
    antigo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    depois = amanha + timedelta(days=3)

    novo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=depois, db=db, remarcar=True
    )

    assert novo.id != antigo.id
    assert scheduling.get(antigo.id, db).status == "cancelado"
    assert scheduling.compromisso_ativo(lead_id, db).id == novo.id


def test_o_antigo_diz_na_ficha_que_foi_remarcado(scheduling, lead_id, amanha, db):
    """Sem a nota, o corretor lê o cancelamento como desistência."""
    antigo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db,
        observacoes="Quer ver os imóveis 142 e 144.",
    )

    scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha + timedelta(days=3),
        db=db, remarcar=True,
    )

    observacoes = scheduling.get(antigo.id, db).observacoes
    assert "Remarcado para" in observacoes
    assert "142" in observacoes


def test_compromisso_encerrado_libera_a_vaga(scheduling, lead_id, amanha, db):
    """Quem desmarcou pode marcar de novo; quem já visitou pode voltar."""
    primeiro = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    scheduling.update_status(primeiro.id, "cancelado", db)

    segundo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha + timedelta(days=5), db=db
    )

    assert segundo.id != primeiro.id


def test_o_banco_tambem_recusa_dois_ativos(scheduling, lead_id, amanha, db):
    """A garantia é do índice, e não da checagem que o serviço faz antes.

    Sem esta prova, trocar o `first()` do serviço por um caminho que não
    consulta deixaria a duplicata voltar em silêncio.
    """
    scheduling.create(lead_id=lead_id, tipo="visita", data_hora=amanha, db=db)

    db.add(Agendamento(
        lead_id=lead_id, tipo="visita", data_hora=amanha + timedelta(days=1),
        status="pendente",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_ressuscitar_um_cancelado_com_outro_de_pe_e_recusado(
    scheduling, lead_id, amanha, db
):
    """Pela tela dá para reabrir um compromisso encerrado; pelo banco, não."""
    antigo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    scheduling.update_status(antigo.id, "cancelado", db)
    scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha + timedelta(days=5), db=db
    )

    with pytest.raises(CompromissoJaMarcado):
        scheduling.update_status(antigo.id, "pendente", db)

    with pytest.raises(CompromissoJaMarcado):
        scheduling.editar(
            antigo.id, db, tipo="visita", data_hora=amanha, status="pendente",
        )


def test_o_proprio_compromisso_pode_mudar_de_status(scheduling, lead_id, amanha, db):
    """A checagem olha o dono: confirmar o que já está de pé não é conflito."""
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    atual = scheduling.update_status(agendamento.id, "confirmado", db)

    assert atual.status == "confirmado"


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
    scheduling, lead_id, amanha, db
):
    """`None` aqui é "o corretor apagou", não "não foi informado".

    É o mesmo critério da edição de lead: o caminho manual precisa conseguir
    limpar o que veio errado da conversa.
    """
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db,
        observacoes="levar a planta",
    )

    scheduling.editar(
        agendamento.id, db, tipo="visita", data_hora=amanha, status="pendente",
        observacoes=None,
    )

    assert scheduling.get(agendamento.id, db).observacoes is None


def test_cancelar_o_ultimo_compromisso_tira_o_lead_de_agendado(
    scheduling, lead_id, amanha, db
):
    """`agendado` afirma que existe visita marcada.

    Cancelar a última torna a afirmação falsa, e o lead precisa voltar para
    onde os dados dele o colocam.
    """
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    assert db.query(Lead).filter(Lead.id == lead_id).one().status == "agendado"

    scheduling.editar(
        agendamento.id, db, tipo="visita", data_hora=amanha, status="cancelado"
    )

    assert db.query(Lead).filter(Lead.id == lead_id).one().status != "agendado"


def test_confirmar_mantem_o_lead_agendado(scheduling, lead_id, amanha, db):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    scheduling.editar(
        agendamento.id, db, tipo="visita", data_hora=amanha, status="confirmado"
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


def test_excluir_o_ultimo_compromisso_tira_o_lead_de_agendado(
    scheduling, lead_id, amanha, db
):
    agendamento = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    scheduling.excluir(agendamento.id, db)

    assert db.query(Lead).filter(Lead.id == lead_id).one().status != "agendado"


def test_excluir_um_compromisso_encerrado_nao_mexe_no_ativo(
    scheduling, lead_id, amanha, db
):
    """Apagar o histórico não tira da agenda o que ainda está de pé."""
    antigo = scheduling.create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )
    scheduling.update_status(antigo.id, "cancelado", db)
    scheduling.create(
        lead_id=lead_id, tipo="reuniao", data_hora=amanha + timedelta(days=2), db=db
    )

    scheduling.excluir(antigo.id, db)

    assert db.query(Lead).filter(Lead.id == lead_id).one().status == "agendado"


def test_lead_qualificado_volta_para_qualificado(scheduling, db):
    """Ele volta para onde os dados o colocam, não para o começo do funil."""
    servico = LeadService()
    lead = servico.criar_lead_manual(
        {
            "intencao": "compra",
            "orcamento_max": 700000,
            "bairro_interesse": "Bela Vista",
            "quartos": 2,
        },
        db,
    )
    agendamento = scheduling.create(
        lead_id=lead.id, tipo="visita", data_hora=datetime.now(UTC) + timedelta(days=1),
        db=db,
    )

    scheduling.excluir(agendamento.id, db)

    assert db.query(Lead).filter(Lead.id == lead.id).one().status == "qualificado"


def test_excluir_agendamento_inexistente_devolve_false(scheduling, db):
    assert scheduling.excluir(999999, db) is False
