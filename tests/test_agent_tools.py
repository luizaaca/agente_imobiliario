"""Testes de contrato das tools e do ciclo de mensagem do agente."""

import asyncio

import pytest
from pydantic_ai.messages import TextPart, UserPromptPart

from src.agent import sdr_agent as agent_mod
from src.agent.history import build_message_history
from src.agent.prompts import HANDOVER_MESSAGE, UNAVAILABLE_MESSAGE
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.models import Agendamento, LLMUsage, Mensagem
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="tool-001", db=db, nome="Ana"
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


def conversar(texto, lead_id, deps, modelo):
    with agent_mod.sdr_agent.override(model=modelo):
        return asyncio.run(process_message(lead_id, texto, "teste", deps()))


# --- Contrato das tools ------------------------------------------------------


def test_todas_as_tools_estao_expostas(llm_fake, lead_id, deps):
    expostas = {}

    def capturar(messages, info):
        expostas["nomes"] = sorted(t.name for t in info.function_tools)
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="ok")])

    from pydantic_ai.models.function import FunctionModel
    conversar("oi", lead_id, deps, FunctionModel(capturar))

    assert expostas["nomes"] == [
        "agendar_reuniao",
        "atualizar_perfil_lead",
        "buscar_imoveis",
        "gerar_resumo_corretor",
        "registrar_qualificacao",
    ]


def test_registrar_qualificacao_persiste_os_campos(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("registrar_qualificacao", {
            "intencao": "compra", "bairro_interesse": "Bela Vista",
            "orcamento_max": 700000, "quartos": 2, "urgencia": "alta",
        }),
        "Registrei tudo!",
    )
    conversar("quero 2 quartos na Bela Vista", lead_id, deps, modelo)

    lead = LeadService().get_lead(lead_id, db)
    assert (lead.intencao, lead.bairro_interesse, lead.quartos) == ("compra", "Bela Vista", 2)
    assert lead.status == "qualificado"


def test_valor_longo_e_recusado_pelo_schema_da_tool(llm_fake, lead_id, deps, db):
    """Regressão: `perfil` com texto longo derrubava o turno com DataError.

    Hoje o `max_length` da tool barra antes de chegar ao banco: o modelo
    recebe o erro de validação e pode corrigir. O turno não quebra e o valor
    invalido não é persistido.
    """
    frase_longa = "Busca de imovel para aluguel na zona leste, com interesse em 1 ou 2 quartos."
    modelo = llm_fake(
        ("registrar_qualificacao", {"intencao": "aluguel", "perfil": frase_longa}),
        "Certo!",
    )
    resposta = conversar("quero alugar", lead_id, deps, modelo)

    assert resposta == "Certo!"
    perfil = LeadService().get_lead(lead_id, db).perfil
    assert perfil != frase_longa
    assert perfil is None or len(perfil) <= 30


def test_valor_longo_que_escapa_do_schema_e_truncado(lead_id, db):
    """Segunda camada: o serviço não confia no schema e trunca mesmo assim."""
    frase_longa = "x" * 200
    LeadService().update_qualification(lead_id, {"perfil": frase_longa}, db)
    assert len(LeadService().get_lead(lead_id, db).perfil) == 30


def test_registrar_qualificacao_descarta_urgencia_invalida(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("registrar_qualificacao", {"intencao": "compra", "urgencia": "muito urgente"}),
        "Ok!",
    )
    conversar("tenho pressa", lead_id, deps, modelo)
    assert LeadService().get_lead(lead_id, db).urgencia is None


def test_buscar_imoveis_devolve_itens_do_catalogo(llm_fake, catalogo, lead_id, deps):
    achados = {}

    def capturar(messages, info):
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        if not achados:
            achados["chamou"] = True
            return ModelResponse(parts=[ToolCallPart(
                tool_name="buscar_imoveis",
                args={"bairro_interesse": "Bela Vista", "limite_resultados": 5},
            )])
        achados["retorno"] = str(messages[-1].parts[0].content)
        return ModelResponse(parts=[TextPart(content="Seguem as opcoes")])

    from pydantic_ai.models.function import FunctionModel
    conversar("o que tem na Bela Vista?", lead_id, deps, FunctionModel(capturar))

    assert "Apartamento Bela Vista Compacto" in achados["retorno"]


def test_buscar_imoveis_sem_resultado_avisa(llm_fake, catalogo, lead_id, deps):
    retornos = {}

    def capturar(messages, info):
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        if not retornos:
            retornos["chamou"] = True
            return ModelResponse(parts=[ToolCallPart(
                tool_name="buscar_imoveis", args={"bairro_interesse": "Inexistente"},
            )])
        retornos["retorno"] = str(messages[-1].parts[0].content)
        return ModelResponse(parts=[TextPart(content="Nada encontrado")])

    from pydantic_ai.models.function import FunctionModel
    conversar("tem algo no bairro Inexistente?", lead_id, deps, FunctionModel(capturar))

    assert "Nenhum imóvel encontrado" in retornos["retorno"]


def test_agendar_reuniao_cria_agendamento(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("agendar_reuniao", {"tipo": "visita", "data_hora": "2027-03-10 15:00"}),
        "Agendado!",
    )
    conversar("quero visitar", lead_id, deps, modelo)

    agendamento = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()
    assert agendamento.tipo == "visita"
    assert LeadService().get_lead(lead_id, db).status == "agendado"


def test_agendar_reuniao_rejeita_data_malformada(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("agendar_reuniao", {"tipo": "visita", "data_hora": "amanha de tarde"}),
        "Pode me dar a data exata?",
    )
    conversar("quero visitar", lead_id, deps, modelo)
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 0


def test_atualizar_perfil_narrativo(llm_fake, lead_id, deps, db):
    texto = "Lead busca apartamento proximo ao metro; rejeitou opcoes sem varanda."
    modelo = llm_fake(
        ("atualizar_perfil_lead", {"perfil_narrativo_atualizado": texto}),
        "Anotado!",
    )
    conversar("nao gostei, quero varanda", lead_id, deps, modelo)
    assert LeadService().get_lead(lead_id, db).perfil_narrativo == texto


def test_gerar_resumo_corretor_persiste_o_resumo(llm_fake, lead_id, deps, db):
    modelo = llm_fake(("gerar_resumo_corretor", {}), "Resumo pronto!")
    conversar("pode passar pro corretor", lead_id, deps, modelo)

    resumo = LeadService().get_lead(lead_id, db).resumo
    assert resumo and "Resumo Executivo" in resumo


# --- Ciclo de mensagem -------------------------------------------------------


def test_mensagens_do_turno_sao_persistidas(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))

    papeis = [m.role for m in db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id).order_by(Mensagem.id)]
    assert papeis == ["user", "assistant"]


def test_consumo_de_llm_e_registrado(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))
    uso = db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).one()
    assert uso.operation == "chat"
    assert uso.conversation_turn == 1


def test_lead_novo_entra_em_qualificacao(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))
    assert LeadService().get_lead(lead_id, db).status == "em_qualificacao"


def test_lead_inativo_e_retomado_ao_responder(llm_fake, lead_id, deps, db):
    LeadService().update_status(lead_id, "inativo", db)
    conversar("voltei!", lead_id, deps, llm_fake("que bom!"))
    assert LeadService().get_lead(lead_id, db).status == "em_qualificacao"


def test_falha_do_provider_nao_propaga(lead_id, deps):
    def explodir(messages, info):
        raise RuntimeError("provider fora do ar")

    from pydantic_ai.models.function import FunctionModel
    resposta = conversar("oi", lead_id, deps, FunctionModel(explodir))
    assert resposta == UNAVAILABLE_MESSAGE


# --- Memória conversacional --------------------------------------------------


def test_primeiro_turno_nao_tem_historico(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append(sum(
            1 for m in messages for p in m.parts if isinstance(p, UserPromptPart)
        ))
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="ok")])

    from pydantic_ai.models.function import FunctionModel
    conversar("primeira", lead_id, deps, FunctionModel(capturar))
    assert capturado == [1]


def test_turnos_seguintes_recebem_o_historico(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append([
            ("U", str(p.content)) if isinstance(p, UserPromptPart) else ("A", str(p.content))
            for m in messages for p in m.parts
            if isinstance(p, (UserPromptPart, TextPart))
        ])
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="resposta")])

    from pydantic_ai.models.function import FunctionModel
    for texto in ("primeira", "segunda", "terceira"):
        conversar(texto, lead_id, deps, FunctionModel(capturar))

    assert capturado[0] == [("U", "primeira")]
    assert capturado[1] == [("U", "primeira"), ("A", "resposta"), ("U", "segunda")]
    assert capturado[2][-1] == ("U", "terceira")
    assert len(capturado[2]) == 5


def test_mensagem_atual_nao_aparece_duplicada(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append([
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        ])
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="resposta")])

    from pydantic_ai.models.function import FunctionModel
    conversar("primeira", lead_id, deps, FunctionModel(capturar))
    conversar("segunda", lead_id, deps, FunctionModel(capturar))

    assert capturado[1].count("segunda") == 1


def test_conversao_de_historico_ignora_papeis_nao_conversacionais(db):
    class MensagemFalsa:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    historico = build_message_history([
        MensagemFalsa("user", "oi"),
        MensagemFalsa("system", "instrucao interna"),
        MensagemFalsa("tool", "resultado de tool"),
        MensagemFalsa("assistant", "ola"),
        MensagemFalsa("user", "   "),
    ])
    assert len(historico) == 2


# --- Limites de custo --------------------------------------------------------


def test_budget_diario_estourado_bloqueia_o_turno(llm_fake, lead_id, deps, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_daily_budget_exceeded", lambda self, db: True
    )
    assert conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui")) == UNAVAILABLE_MESSAGE


def test_budget_mensal_estourado_bloqueia_o_turno(llm_fake, lead_id, deps, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_monthly_budget_exceeded", lambda self, db: True
    )
    assert conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui")) == UNAVAILABLE_MESSAGE


def test_limite_da_conversa_faz_handover_com_resumo(llm_fake, lead_id, deps, db, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    resposta = conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui"))

    assert resposta == HANDOVER_MESSAGE
    assert LeadService().get_lead(lead_id, db).resumo
    assert LeadService().has_message_type(lead_id, "handover", db)


def test_handover_nao_se_repete(llm_fake, lead_id, deps, db, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    for _ in range(3):
        conversar("oi", lead_id, deps, llm_fake("x"))

    handovers = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "handover"
    ).count()
    assert handovers == 1
