"""Confirmar e cancelar compromisso pela conversa.

Estes testes nascem de um defeito real: sem ferramenta para confirmar, o
agente chamou `agendar_reuniao` de novo — criando uma segunda visita para o
mesmo horário — e anunciou "Visita confirmada com sucesso!" numa resposta que,
três linhas abaixo, imprimia `Status: pendente`.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from src.agent import sdr_agent as agent_mod
from src.agent.sdr_agent import SDRDependencies, montar_contexto_do_lead, process_message
from src.db.models import Agendamento, Mensagem
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.tempo import UTC, formatar


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="agenda-conversa", db=db, nome="Ana"
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


@pytest.fixture
def amanha():
    return datetime.now() + timedelta(days=1)


@pytest.fixture
def agendamento(lead_id, amanha, db):
    return SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )


def _apresentar(lead_id, ids, db):
    """Registra que estes imóveis já foram mostrados a este lead.

    É de onde `imoveis_apresentados` lê: o `metadata_json` da mensagem de
    ferramenta, e não o texto dela, que volta abreviado ao histórico.
    """
    db.add(Mensagem(
        lead_id=lead_id, channel="teste", role="tool",
        content="Encontrei 2 imóvel(is).", message_type="chat",
        metadata_json={"tool_name": "buscar_imoveis", "busca": {"imovel_ids": ids}},
    ))
    db.commit()


def _chamar(tool, args, lead_id, deps, db):
    """Roda um turno em que o modelo chama a tool e devolve o que ela respondeu.

    As tools gravam por sessões próprias (`get_db()`), então sem expirar a
    identity map o teste continuaria enxergando o objeto antigo.
    """
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


# --- Listar ------------------------------------------------------------------
#
# A lista tambem abre as instrucoes, mas la ela fica antes de toda a conversa.
# Quando o historico recente contradiz — o agente repetindo que nao acha os IDs
# —, o modelo segue o que esta perto. A tool devolve a mesma verdade no fim.


def test_listar_devolve_os_compromissos_com_id(agendamento, lead_id, deps, db):
    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert f"ID {agendamento.id}" in retorno
    assert "Compromisso marcado —" in retorno


def test_listar_sem_nenhum_diz_isso(lead_id, deps, db):
    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado: nenhum" in retorno


def test_listar_nao_mostra_compromisso_de_outro_lead(lead_id, deps, amanha, db):
    outro = LeadService().get_or_create_lead(
        channel="teste", external_id="alheio-na-lista", db=db
    )
    alheio = SchedulingService().create(
        lead_id=outro.id, tipo="visita", data_hora=amanha, db=db
    )

    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert f"ID {alheio.id}" not in retorno


def test_listar_reflete_o_cancelamento(agendamento, lead_id, deps, db):
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado: nenhum" in retorno


# --- Confirmar ---------------------------------------------------------------


def test_confirmar_muda_o_status(agendamento, lead_id, deps, db):
    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": agendamento.id}, lead_id, deps, db)

    assert "confirmado" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "confirmado"


def test_confirmar_o_que_ja_estava_confirmado_nao_mente(
    agendamento, lead_id, deps, db
):
    SchedulingService().update_status(agendamento.id, "confirmado", db)

    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": agendamento.id}, lead_id, deps, db)

    assert "já estava confirmado" in retorno


def test_confirmar_compromisso_cancelado_e_recusado(agendamento, lead_id, deps, db):
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": agendamento.id}, lead_id, deps, db)

    assert "não pode ser confirmado" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "cancelado"


def test_id_inventado_volta_como_erro_em_vez_de_derrubar_o_turno(
    agendamento, lead_id, deps, db
):
    """A recusa traz os IDs válidos, para o modelo se corrigir na retentativa.

    Só dizer "não existe" fez o agente desistir e contar isso à pessoa, depois
    de pegar no histórico o ID de um compromisso já apagado.
    """
    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": 999999}, lead_id, deps, db)

    assert "Não existe compromisso 999999" in retorno
    assert f"ID {agendamento.id}" in retorno


def test_id_errado_sem_nenhum_compromisso_manda_agendar(lead_id, deps, db):
    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": 999999}, lead_id, deps, db)

    assert "não tem nenhum marcado" in retorno
    assert "agendar_reuniao" in retorno


def test_compromisso_de_outro_lead_nao_e_alcancavel(lead_id, deps, amanha, db):
    """Mesmo cuidado que `agendar_reuniao` toma com `imovel_id`."""
    outro = LeadService().get_or_create_lead(
        channel="teste", external_id="outro-lead", db=db
    )
    alheio = SchedulingService().create(
        lead_id=outro.id, tipo="visita", data_hora=amanha, db=db
    )

    retorno = _chamar(
        "confirmar_agendamento", {"agendamento_id": alheio.id}, lead_id, deps, db)

    assert "Não existe compromisso" in retorno
    assert SchedulingService().get(alheio.id, db).status == "pendente"


# --- Cancelar ----------------------------------------------------------------


def test_cancelar_muda_o_status_e_registra_o_motivo(agendamento, lead_id, deps, db):
    retorno = _chamar(
        "cancelar_agendamento",
        {"agendamento_id": agendamento.id, "motivo": "viajou na data"},
        lead_id, deps, db)

    assert "cancelado" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "cancelado"

    aviso = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "system_notice"
    ).one()
    assert "viajou na data" in aviso.content


def test_cancelar_o_ultimo_compromisso_tira_o_lead_de_agendado(
    agendamento, lead_id, deps, db
):
    assert LeadService().get_lead(lead_id, db).status == "agendado"

    _chamar(
        "cancelar_agendamento",
        {"agendamento_id": agendamento.id, "motivo": "desistiu"},
        lead_id, deps, db)

    assert LeadService().get_lead(lead_id, db).status != "agendado"


# --- Duplicata ---------------------------------------------------------------


def test_agendar_duas_vezes_o_mesmo_compromisso_nao_duplica(catalogo, lead_id, deps, db):
    """O defeito original: confirmar virava um segundo agendamento igual."""
    args = {"tipo": "visita", "data_hora": "2027-03-10 15:00"}

    _chamar("agendar_reuniao", args, lead_id, deps, db)
    retorno = _chamar("agendar_reuniao", args, lead_id, deps, db)

    agendamentos = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).all()
    assert len(agendamentos) == 1
    assert str(agendamentos[0].id) in retorno


def test_horario_diferente_sem_remarcar_nao_cria_segundo(catalogo, lead_id, deps, db):
    """Pode ser remarcação, pode ser o modelo esquecendo o que já marcou."""
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-11 15:00"},
        lead_id, deps, db)

    linhas = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).all()
    assert len(linhas) == 1
    assert formatar(linhas[0].data_hora) == "10/03/2027 às 15:00"


def test_mesmo_horario_depois_de_cancelar_pode_ser_remarcado(
    agendamento, lead_id, deps, amanha, db
):
    """Cancelado não bloqueia o horário: a pessoa pode voltar atrás."""
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    novo = SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    assert novo.id != agendamento.id


# --- Contexto ----------------------------------------------------------------


def test_contexto_lista_os_compromissos_com_id(agendamento, lead_id, db):
    """Sem os IDs no contexto o modelo não tem de onde tirar o argumento."""
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Compromisso marcado —" in contexto
    assert f"ID {agendamento.id}" in contexto


def test_contexto_manda_ignorar_ids_antigos_da_conversa(agendamento, lead_id, db):
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Ignore qualquer ID citado antes na conversa" in contexto


def test_sem_compromisso_o_contexto_diz_isso_explicitamente(lead_id, db):
    """O silêncio deixaria o modelo acreditar no que a conversa disse antes."""
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Compromisso marcado: nenhum" in contexto


def test_compromisso_cancelado_sai_do_contexto(agendamento, lead_id, db):
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert f"ID {agendamento.id}" not in contexto
    assert "Compromisso marcado: nenhum" in contexto

# --- A visita diz o que sera visitado ----------------------------------------
#
# O compromisso nao aponta mais para uma linha do catalogo: quem diz isso ao
# corretor e a `observacoes`, e e ela que ele le junto do perfil e do resumo.


def test_visita_sem_imoveis_na_observacao_e_recusada(lead_id, deps, db):
    """Vazia, o handover vira um horario e nada mais.

    Aconteceu de verdade: o agente marcou "sabado as 10h na Bela Vista" e o
    corretor ficou sem saber aonde ir.
    """
    _apresentar(lead_id, [142, 144], db)

    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert "não diz o que será visitado" in retorno
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 0


def test_numero_que_nao_e_imovel_nao_serve(lead_id, deps, db):
    """"sabado as 10h" tem digito e nao diz imovel nenhum."""
    _apresentar(lead_id, [142, 144], db)

    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Visita sábado às 10h, perto do metrô."},
        lead_id, deps, db)

    assert "não diz o que será visitado" in retorno


def test_a_recusa_entrega_os_ids_que_servem(lead_id, deps, db):
    """Sem saida clara o modelo insiste no erro ate estourar as retentativas."""
    _apresentar(lead_id, [142, 144], db)

    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert "142" in retorno and "144" in retorno
    # `detalhar_imoveis` e nao `buscar_imoveis`: o ID que falta e de um imovel
    # ja apresentado, e buscar de novo custa dezenas de milhares de tokens.
    assert "detalhar_imoveis" in retorno


def test_observacao_com_o_id_do_imovel_passa(lead_id, deps, db):
    _apresentar(lead_id, [142, 144], db)

    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver os imóveis 142 e 144; vai com o marido."},
        lead_id, deps, db)

    guardado = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()
    assert "142" in guardado.observacoes


def test_sem_imovel_apresentado_nao_ha_o_que_cobrar(lead_id, deps, db):
    """Lead criado a mao, conversa que comecou pelo agendamento."""
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 1


def test_reuniao_nao_precisa_de_imovel(lead_id, deps, db):
    """Nem todo encontro e num imovel do catalogo."""
    _apresentar(lead_id, [142], db)

    _chamar(
        "agendar_reuniao",
        {"tipo": "reuniao", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 1


# --- Um compromisso por pessoa -----------------------------------------------


def test_marcar_sobre_um_compromisso_de_pe_avisa_e_nao_marca(
    agendamento, lead_id, deps, db
):
    """A correção não está com o modelo, está com a pessoa: ele tem de perguntar."""
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert "já tem visita marcada" in retorno
    assert "remarcar=true" in retorno
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 1


def test_o_aviso_entrega_o_id_para_confirmar(agendamento, lead_id, deps, db):
    """Ela pode só estar confirmando o que já existe, e aí o caminho é outro."""
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert f"ID {agendamento.id}" in retorno
    assert "confirmar_agendamento" in retorno


def test_remarcar_troca_o_horario_e_guarda_o_antigo(
    agendamento, lead_id, deps, db
):
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00", "remarcar": True},
        lead_id, deps, db)

    linhas = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).all()
    assert len(linhas) == 2
    assert {a.status for a in linhas} == {"cancelado", "pendente"}
    antigo = next(a for a in linhas if a.id == agendamento.id)
    assert "Remarcado para" in antigo.observacoes


# --- Fuso horario ------------------------------------------------------------


def test_a_hora_combinada_e_a_hora_que_o_lead_ve(catalogo, lead_id, deps, db):
    """O container roda em UTC; sem converter, "15h" virava meio-dia aqui.

    Guardar sem fuso fazia o Postgres assumir UTC: o lead 32 pediu 15h e o
    banco ficou com 15:00+00, que em Sao Paulo e 12:00.
    """
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    guardado = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()

    assert formatar(guardado.data_hora) == "10/03/2027 às 15:00"
    assert guardado.data_hora.astimezone(UTC).hour == 18  # 15h de SP sao 18h UTC


def test_o_contexto_mostra_a_hora_no_relogio_do_lead(catalogo, lead_id, deps, db):
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "15:00" in contexto
