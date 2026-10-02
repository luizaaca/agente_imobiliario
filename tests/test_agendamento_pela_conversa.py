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
# A mesma verdade abre as instrucoes, mas la ela fica antes de toda a conversa.
# Quando o historico recente contradiz, o modelo segue o que esta perto — e a
# tool responde de novo no fim do turno.


def test_listar_devolve_o_compromisso_marcado(agendamento, lead_id, deps, db):
    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado —" in retorno
    assert formatar(agendamento.data_hora) in retorno


def test_listar_nao_expoe_id(agendamento, lead_id, deps, db):
    """Nenhuma tool recebe qual compromisso, entao nao ha ID a guardar.

    Enquanto havia, o modelo pegava numeros antigos do historico e chamava
    confirmar com o ID de um compromisso ja apagado.
    """
    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert f"ID {agendamento.id}" not in retorno


def test_listar_sem_nenhum_diz_isso(lead_id, deps, db):
    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado: nenhum" in retorno


def test_listar_nao_alcanca_o_compromisso_de_outro_lead(lead_id, deps, amanha, db):
    outro = LeadService().get_or_create_lead(
        channel="teste", external_id="alheio-na-lista", db=db
    )
    SchedulingService().create(
        lead_id=outro.id, tipo="visita", data_hora=amanha, db=db
    )

    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado: nenhum" in retorno


def test_listar_reflete_o_cancelamento(agendamento, lead_id, deps, db):
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    retorno = _chamar("listar_agendamentos", {}, lead_id, deps, db)

    assert "Compromisso marcado: nenhum" in retorno


# --- Confirmar ---------------------------------------------------------------


def test_confirmar_muda_o_status(agendamento, lead_id, deps, db):
    retorno = _chamar("confirmar_agendamento", {}, lead_id, deps, db)

    assert "Confirmado" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "confirmado"


def test_confirmar_o_que_ja_estava_confirmado_nao_mente(
    agendamento, lead_id, deps, db
):
    SchedulingService().update_status(agendamento.id, "confirmado", db)

    retorno = _chamar("confirmar_agendamento", {}, lead_id, deps, db)

    assert "já estava confirmada" in retorno


def test_confirmar_sem_compromisso_manda_agendar(lead_id, deps, db):
    """Dizer so "nao existe" fazia o modelo desistir e contar isso a pessoa."""
    retorno = _chamar("confirmar_agendamento", {}, lead_id, deps, db)

    assert "não tem compromisso de pé" in retorno
    assert "agendar_reuniao" in retorno


def test_confirmar_nao_ressuscita_o_cancelado(agendamento, lead_id, deps, db):
    """Cancelado nao esta de pe: para o agente, e como se nao houvesse nada."""
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    retorno = _chamar("confirmar_agendamento", {}, lead_id, deps, db)

    assert "não tem compromisso de pé" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "cancelado"


def test_o_compromisso_de_outro_lead_nao_e_alcancavel(lead_id, deps, amanha, db):
    """A tool nao recebe qual compromisso: o dono e sempre o lead do turno.

    Enquanto o ID era argumento, erra-lo alcancava a agenda de outra pessoa —
    e a checagem de dono existia justamente para isso.
    """
    outro = LeadService().get_or_create_lead(
        channel="teste", external_id="outro-lead", db=db
    )
    alheio = SchedulingService().create(
        lead_id=outro.id, tipo="visita", data_hora=amanha, db=db
    )

    retorno = _chamar("confirmar_agendamento", {}, lead_id, deps, db)

    assert "não tem compromisso de pé" in retorno
    assert SchedulingService().get(alheio.id, db).status == "pendente"


# --- Cancelar ----------------------------------------------------------------


def test_cancelar_muda_o_status_e_registra_o_motivo(agendamento, lead_id, deps, db):
    retorno = _chamar(
        "cancelar_agendamento", {"motivo": "viajou na data"}, lead_id, deps, db)

    assert "Cancelado" in retorno
    assert SchedulingService().get(agendamento.id, db).status == "cancelado"

    aviso = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "system_notice"
    ).one()
    assert "viajou na data" in aviso.content


def test_cancelar_o_ultimo_compromisso_tira_o_lead_de_agendado(
    agendamento, lead_id, deps, db
):
    assert LeadService().get_lead(lead_id, db).status == "agendado"

    _chamar("cancelar_agendamento", {"motivo": "desistiu"}, lead_id, deps, db)

    assert LeadService().get_lead(lead_id, db).status != "agendado"


def test_cancelar_sem_compromisso_nao_derruba_o_turno(lead_id, deps, db):
    retorno = _chamar(
        "cancelar_agendamento", {"motivo": "desistiu"}, lead_id, deps, db)

    assert "não tem compromisso de pé" in retorno


# --- Duplicata ---------------------------------------------------------------


def test_agendar_duas_vezes_o_mesmo_compromisso_nao_duplica(catalogo, lead_id, deps, db):
    """O defeito original: confirmar virava um segundo agendamento igual."""
    args = {"tipo": "visita", "data_hora": "2027-03-10 15:00",
            "observacoes": "Quer ver o imóvel 142."}

    _chamar("agendar_reuniao", args, lead_id, deps, db)
    retorno = _chamar("agendar_reuniao", args, lead_id, deps, db)

    agendamentos = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).all()
    assert len(agendamentos) == 1
    assert "2027-03-10 15:00" in retorno


def test_horario_diferente_sem_remarcar_nao_cria_segundo(catalogo, lead_id, deps, db):
    """Pode ser remarcação, pode ser o modelo esquecendo o que já marcou."""
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver o imóvel 142."},
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


def test_contexto_traz_o_compromisso_e_nenhum_id(agendamento, lead_id, db):
    """O horário é o que a conversa precisa; o ID não é argumento de nada."""
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Compromisso marcado —" in contexto
    assert formatar(agendamento.data_hora) in contexto
    assert f"ID {agendamento.id}" not in contexto


def test_o_contexto_se_declara_acima_da_conversa(agendamento, lead_id, db):
    """O histórico pode citar um compromisso que já mudou desde então."""
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "acima do que a conversa disser" in contexto


def test_sem_compromisso_o_contexto_diz_isso_explicitamente(lead_id, db):
    """O silêncio deixaria o modelo acreditar no que a conversa disse antes."""
    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Compromisso marcado: nenhum" in contexto


def test_compromisso_cancelado_sai_do_contexto(agendamento, lead_id, db):
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "Compromisso marcado: nenhum" in contexto

# --- A visita diz o que sera visitado ----------------------------------------
#
# O compromisso nao aponta para uma linha do catalogo: quem diz isso ao
# corretor e a `observacoes`, e e ela que ele le junto do perfil e do resumo.


def test_visita_sem_observacao_e_recusada(lead_id, deps, db):
    """Vazia, o handover vira um horario e nada mais.

    Aconteceu de verdade: o agente marcou "sabado as 10h na Bela Vista" e o
    corretor ficou sem saber aonde ir.
    """
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert "não diz o que será visitado" in retorno
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 0


def test_observacao_so_de_espacos_nao_conta(lead_id, deps, db):
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00", "observacoes": "   "},
        lead_id, deps, db)

    assert "não diz o que será visitado" in retorno


def test_a_recusa_diz_o_que_escrever(lead_id, deps, db):
    """Sem saida clara o modelo insiste no erro ate estourar as retentativas."""
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00"},
        lead_id, deps, db)

    assert "ID de cada" in retorno
    # `detalhar_imoveis` e nao `buscar_imoveis`: o ID que falta e de um imovel
    # ja apresentado, e buscar de novo custa dezenas de milhares de tokens.
    assert "detalhar_imoveis" in retorno


def test_a_observacao_e_guardada_como_veio(lead_id, deps, db):
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver os imóveis 142 e 144; vai com o marido."},
        lead_id, deps, db)

    guardado = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()
    assert guardado.observacoes == "Quer ver os imóveis 142 e 144; vai com o marido."


def test_o_conteudo_da_observacao_nao_e_conferido(lead_id, deps, db):
    """So se cobra que exista.

    Adivinhar se um texto livre cita imovel — e se o ID e de um ja apresentado
    — erraria nos dois sentidos, e o preco do falso negativo e recusar um
    agendamento que a pessoa acabou de combinar.
    """
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Vai levar a mãe; prefere subir de elevador."},
        lead_id, deps, db)

    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 1


def test_reuniao_nao_precisa_de_observacao(lead_id, deps, db):
    """Nem todo encontro e num imovel do catalogo."""
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
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver o imóvel 142."},
        lead_id, deps, db)

    assert "já tem visita marcada" in retorno
    assert "remarcar=true" in retorno
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 1


def test_o_aviso_aponta_a_saida_de_confirmar(agendamento, lead_id, deps, db):
    """Ela pode só estar confirmando o que já existe, e aí o caminho é outro."""
    retorno = _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver o imóvel 142."},
        lead_id, deps, db)

    assert "confirmar_agendamento" in retorno
    assert f"ID {agendamento.id}" not in retorno


def test_remarcar_troca_o_horario_e_guarda_o_antigo(
    agendamento, lead_id, deps, db
):
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Trocou para o imóvel 144.", "remarcar": True},
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
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver o imóvel 142."},
        lead_id, deps, db)

    guardado = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()

    assert formatar(guardado.data_hora) == "10/03/2027 às 15:00"
    assert guardado.data_hora.astimezone(UTC).hour == 18  # 15h de SP sao 18h UTC


def test_o_contexto_mostra_a_hora_no_relogio_do_lead(catalogo, lead_id, deps, db):
    _chamar(
        "agendar_reuniao",
        {"tipo": "visita", "data_hora": "2027-03-10 15:00",
         "observacoes": "Quer ver o imóvel 142."},
        lead_id, deps, db)

    contexto = montar_contexto_do_lead(LeadService().get_lead(lead_id, db))

    assert "15:00" in contexto
