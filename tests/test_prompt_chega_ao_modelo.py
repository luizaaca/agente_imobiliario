"""As instruções do agente precisam chegar ao modelo em TODO turno.

Estes testes nascem de um defeito que passou por baixo de toda a suíte: o
contexto do lead era montado certo — havia teste para isso — e mesmo assim não
chegava ao modelo. O pydantic-ai só insere o `system_prompt` quando o
`message_history` está vazio, e como aqui o histórico é reidratado do banco a
cada turno, da segunda mensagem em diante o agente rodava sem prompt nenhum:
sem persona, sem regras, sem os IDs dos compromissos.

Por isso estes testes olham o que o MODELO recebeu, e não o que a função
`montar_contexto_do_lead` devolveu.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from src.agent import sdr_agent as agent_mod
from src.agent.sdr_agent import SDRDependencies, process_message
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="prompt-no-modelo", db=db, nome="Ana"
    ).id


@pytest.fixture
def deps(lead_id):
    return SDRDependencies(
        lead_id=lead_id,
        channel="teste",
        lead_service=LeadService(),
        catalog_service=CatalogService(),
        scheduling_service=SchedulingService(),
        llm_usage_service=LLMUsageService(),
    )


def _turno(lead_id, deps, texto="e aí?"):
    """Roda um turno e devolve tudo que o modelo recebeu, como um texto só."""
    recebido = {}

    def modelo(messages, info):
        recebido["instrucoes"] = info.instructions or ""
        recebido["partes"] = [
            str(getattr(parte, "content", "")) for msg in messages for parte in msg.parts
        ]
        return ModelResponse(parts=[TextPart(content="ok")])

    with agent_mod.sdr_agent.override(model=FunctionModel(modelo)):
        asyncio.run(process_message(lead_id, texto, "teste", deps))

    return recebido["instrucoes"] + "\n".join(recebido["partes"])


def _conversar(lead_id, deps, quantos=2):
    """Deixa turnos para trás, que é quando o histórico deixa de estar vazio."""
    for _ in range(quantos):
        _turno(lead_id, deps)


def test_primeiro_turno_leva_as_instrucoes(lead_id, deps):
    assert "corretor" in _turno(lead_id, deps).lower()


def test_turno_com_historico_tambem_leva_as_instrucoes(lead_id, deps):
    """O defeito: da segunda mensagem em diante o modelo rodava sem nada."""
    _conversar(lead_id, deps)

    assert "corretor" in _turno(lead_id, deps).lower()


def test_turno_com_historico_leva_o_contexto_do_lead(lead_id, deps, db):
    LeadService().update_qualification(
        lead_id, {"intencao": "aluguel", "bairro_interesse": "Mooca"}, db
    )
    _conversar(lead_id, deps)

    recebido = _turno(lead_id, deps)

    assert "aluguel" in recebido
    assert "Mooca" in recebido


def test_turno_com_historico_leva_os_ids_dos_compromissos(lead_id, deps, db):
    """Sem isto o modelo chuta o argumento — e chutou o ID do imóvel."""
    agendamento = SchedulingService().create(
        lead_id=lead_id,
        tipo="visita",
        data_hora=datetime.now() + timedelta(days=1),
        db=db,
    )
    _conversar(lead_id, deps)

    assert f"ID {agendamento.id}" in _turno(lead_id, deps)


def test_contexto_do_turno_reflete_o_banco_agora(lead_id, deps, db):
    """As instruções são remontadas a cada turno, não congeladas no primeiro."""
    _conversar(lead_id, deps)
    agendamento = SchedulingService().create(
        lead_id=lead_id,
        tipo="visita",
        data_hora=datetime.now() + timedelta(days=1),
        db=db,
    )

    assert f"ID {agendamento.id}" in _turno(lead_id, deps)
