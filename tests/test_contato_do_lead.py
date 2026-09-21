"""Nome e telefone: o agente não tinha onde gravar nem quando pedir.

Nenhum dos leads da POC tinha nome ou telefone — `registrar_qualificacao` não
expunha os dois campos, então o modelo podia ouvir e não tinha o que fazer com
aquilo. Uma visita marcada sem telefone não serve ao corretor, que é quem liga.
"""

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from src.agent import sdr_agent as agent_mod
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.sdr_agent import SDRDependencies, process_message
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="contato-001", db=db
    ).id


@pytest.fixture
def deps(lead_id):
    def criar():
        return SDRDependencies(
            lead_id=lead_id,
            channel="teste",
            lead_service=LeadService(),
            catalog_service=CatalogService(),
            scheduling_service=SchedulingService(),
            llm_usage_service=LLMUsageService(),
        )
    return criar


def _chamar(tool, args, lead_id, deps, db) -> str:
    capturado = {}

    def modelo(messages, info):
        if not capturado:
            capturado["chamou"] = True
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=args)])
        capturado["retorno"] = str(messages[-1].parts[0].content)
        return ModelResponse(parts=[TextPart(content="ok")])

    with agent_mod.sdr_agent.override(model=FunctionModel(modelo)):
        asyncio.run(process_message(lead_id, "texto", "teste", deps()))
    db.expire_all()
    return capturado["retorno"]


# --- Gravar ------------------------------------------------------------------


def test_nome_e_gravado(lead_id, deps, db):
    _chamar("registrar_qualificacao", {"nome": "Ana"}, lead_id, deps, db)

    assert LeadService().get_lead(lead_id, db).nome == "Ana"


def test_telefone_e_gravado(lead_id, deps, db):
    _chamar(
        "registrar_qualificacao", {"telefone": "11987654321"}, lead_id, deps, db
    )

    assert LeadService().get_lead(lead_id, db).telefone == "(11) 98765-4321"


@pytest.mark.parametrize("escrito", [
    "11987654321",
    "(11) 98765-4321",
    "11 98765 4321",
    "+55 11 98765-4321",
    "5511987654321",
])
def test_o_jeito_de_escrever_nao_importa(escrito, lead_id, deps, db):
    """A pessoa digita de todo jeito; a ficha do corretor não pode refletir isso."""
    _chamar("registrar_qualificacao", {"telefone": escrito}, lead_id, deps, db)

    assert LeadService().get_lead(lead_id, db).telefone == "(11) 98765-4321"


def test_fixo_de_dez_digitos_tambem_vale(lead_id, deps, db):
    _chamar("registrar_qualificacao", {"telefone": "1132654321"}, lead_id, deps, db)

    assert LeadService().get_lead(lead_id, db).telefone == "(11) 3265-4321"


def test_numero_sem_ddd_e_recusado_pedindo_o_ddd(lead_id, deps, db):
    """Gravar incompleto só se descobre errado na hora em que o corretor liga."""
    retorno = _chamar(
        "registrar_qualificacao", {"telefone": "98765-4321"}, lead_id, deps, db
    )

    assert "DDD" in retorno
    assert LeadService().get_lead(lead_id, db).telefone is None


def test_telefone_invalido_nao_derruba_o_resto_da_qualificacao(lead_id, deps, db):
    """A recusa é do campo, não do turno: o modelo corrige e segue."""
    _chamar(
        "registrar_qualificacao", {"telefone": "sei la"}, lead_id, deps, db
    )

    assert LeadService().get_lead(lead_id, db).telefone is None


# --- Pedir na hora certa -----------------------------------------------------


def test_agendar_sem_contato_cobra_os_dois(lead_id, deps, db):
    """É aqui que o dado deixa de ser curiosidade: um corretor vai ligar."""
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-05-10 15:00"},
        lead_id, deps, db,
    )

    assert "o nome nem o telefone" in retorno
    assert "registrar_qualificacao" in retorno


def test_agendar_so_cobra_o_que_falta(lead_id, deps, db):
    LeadService().update_qualification(lead_id, {"nome": "Ana"}, db)

    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-05-10 15:00"},
        lead_id, deps, db,
    )

    assert "o telefone" in retorno
    assert "o nome nem" not in retorno


def test_agendar_com_contato_completo_nao_cobra_nada(lead_id, deps, db):
    LeadService().update_qualification(
        lead_id, {"nome": "Ana", "telefone": "(11) 98765-4321"}, db
    )

    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-05-10 15:00"},
        lead_id, deps, db,
    )

    assert "Você ainda não tem" not in retorno


# --- O que o prompt manda ----------------------------------------------------
#
# Estes testes olham a INTENCAO do prompt, nao a redacao dele. A primeira
# versao prendia frases inteiras ("Pergunte o nome cedo") e quebrou na primeira
# reescrita, sem que nada de fato tivesse se perdido — falso alarme e teste que
# atrapalha em vez de proteger. O prompt e a parte que mais se reescreve; o que
# nao pode sumir dele e a ordem de coletar contato, gravar e amarrar o telefone
# ao agendamento.


def _trechos(texto: str) -> list[str]:
    """O prompt quebrado em trechos curtos, minusculos, para ver co-ocorrencia.

    Duas palavras no mesmo trecho dizem que a instrucao liga uma coisa a outra;
    espalhadas pelo texto inteiro nao dizem nada.
    """
    partes = [texto]
    for separador in ("\n", ". ", "; "):
        partes = [p for parte in partes for p in parte.split(separador)]
    return [p.lower() for p in partes if p.strip()]


def _algum_trecho_com(texto: str, *palavras: str) -> bool:
    return any(all(p in trecho for p in palavras) for trecho in _trechos(texto))


def test_o_prompt_manda_coletar_nome_e_telefone():
    """Sem isto o agente conversa bem e não deixa como o corretor ligar."""
    assert _algum_trecho_com(SYSTEM_PROMPT, "nome")
    assert _algum_trecho_com(SYSTEM_PROMPT, "telefone")


def test_o_prompt_liga_o_telefone_ao_agendamento():
    """Telefone pedido no começo vira cadastro; pedido na visita tem motivo.

    Não importa como está escrito, desde que as duas coisas apareçam juntas na
    mesma instrução.
    """
    assert _algum_trecho_com(SYSTEM_PROMPT, "telefone", "agend")


def test_o_prompt_diz_onde_gravar_o_contato():
    """Ouvir o dado e não gravar deixa a ficha do corretor vazia do mesmo jeito."""
    assert _algum_trecho_com(SYSTEM_PROMPT, "registrar_qualificacao", "nome")
