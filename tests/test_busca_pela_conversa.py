"""A tool de busca vista de fora: o que o modelo manda e o que ele recebe.

Os testes do `CatalogService` cobrem o SQL. Estes cobrem a camada que o modelo
enxerga — o schema que ele preenche e o texto que volta — porque foi ali que os
defeitos reais apareceram: a pessoa pediu galpão e recebeu sala comercial, e a
busca saiu com a cidade no campo de bairro.
"""

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from src.agent import sdr_agent as agent_mod
from src.agent.sdr_agent import SDRDependencies, process_message
from src.services.catalog_service import (
    PERFIS_INDICADOS,
    TIPOS,
    ZONAS,
    CatalogService,
)
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="busca-conversa", db=db, nome="Ana"
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


def _buscar(args, lead_id, deps) -> str:
    """Roda um turno em que o modelo chama a busca e devolve o que a tool disse."""
    capturado = {}

    def modelo(messages, info):
        if not capturado:
            capturado["chamou"] = True
            return ModelResponse(
                parts=[ToolCallPart(tool_name="buscar_imoveis", args=args)]
            )
        capturado["retorno"] = str(messages[-1].parts[0].content)
        return ModelResponse(parts=[TextPart(content="ok")])

    with agent_mod.sdr_agent.override(model=FunctionModel(modelo)):
        asyncio.run(process_message(lead_id, "busque", "teste", deps()))
    return capturado["retorno"]


def _schema(lead_id, deps) -> dict:
    """O schema de `buscar_imoveis` exatamente como o provider o recebe."""
    visto = {}

    def modelo(messages, info):
        visto["tools"] = info.function_tools
        return ModelResponse(parts=[TextPart(content="ok")])

    with agent_mod.sdr_agent.override(model=FunctionModel(modelo)):
        asyncio.run(process_message(lead_id, "oi", "teste", deps()))

    tool = next(t for t in visto["tools"] if t.name == "buscar_imoveis")
    return tool.parameters_json_schema


def _enum(schema: dict, campo: str) -> list:
    """Os valores aceitos de um parâmetro, que o `Optional` embrulha em anyOf."""
    prop = schema["properties"][campo]
    if "enum" in prop:
        return prop["enum"]
    return next(a["enum"] for a in prop["anyOf"] if "enum" in a)


# --- O que o modelo vê -------------------------------------------------------


def test_o_vocabulario_do_catalogo_vai_no_schema(lead_id, deps):
    """Enum no schema em vez de instrução em prosa: o valor inválido nem passa."""
    schema = _schema(lead_id, deps)

    assert _enum(schema, "tipo") == list(TIPOS)
    assert _enum(schema, "zona") == list(ZONAS)
    assert _enum(schema, "perfil_indicado") == list(PERFIS_INDICADOS)
    assert _enum(schema, "operacao") == ["venda", "aluguel"]


def test_todo_parametro_da_busca_e_descrito(lead_id, deps):
    """Descrição de parâmetro é o que mais muda o acerto de uma tool."""
    props = _schema(lead_id, deps)["properties"]

    sem_descricao = [nome for nome, p in props.items() if not p.get("description")]
    assert sem_descricao == []


def test_a_descricao_do_bairro_avisa_para_nao_mandar_a_cidade(lead_id, deps):
    """O lead 43 disse "galpão em sp" e o modelo mandou SP como bairro."""
    bairro = _schema(lead_id, deps)["properties"]["bairro"]["description"]

    assert "São Paulo" in bairro and "zera a busca" in bairro


def test_a_descricao_do_preco_avisa_da_escala(lead_id, deps):
    """Teto de 5.000 numa busca de venda não acha nada, e o modelo não sabia."""
    preco = _schema(lead_id, deps)["properties"]["preco_max"]["description"]

    assert "MENSAL" in preco and "TOTAL" in preco


# --- O que a tool devolve ----------------------------------------------------


def test_tipo_pedido_e_tipo_devolvido(catalogo, lead_id, deps):
    retorno = _buscar({"tipo": "galpao"}, lead_id, deps)

    assert "Galpao Belem Logistico" in retorno
    assert "Sala Comercial Paulista" not in retorno


def test_o_que_nao_existe_volta_com_os_numeros_do_catalogo(catalogo, lead_id, deps):
    """"Não achei" sozinho faz o agente pedir desculpa no vazio."""
    retorno = _buscar(
        {"tipo": "galpao", "operacao": "aluguel", "preco_max": 3000}, lead_id, deps
    )

    assert "Nenhum imóvel encontrado" in retorno
    assert "1 galpao para alugar" in retorno
    assert "R$ 18.000" in retorno
    assert "Não ofereça um imóvel de outro tipo" in retorno


def test_preco_sai_no_formato_brasileiro(catalogo, lead_id, deps):
    """"R$ 12,500" em português se lê doze reais e meio."""
    retorno = _buscar({"tipo": "galpao"}, lead_id, deps)

    assert "R$ 18.000" in retorno
    assert "R$ 18,000" not in retorno


def test_aluguel_mostra_o_custo_total_do_mes(catalogo, lead_id, deps):
    retorno = _buscar({"tipo": "sala_comercial"}, lead_id, deps)

    assert "R$ 4.500 + condomínio R$ 900 = R$ 5.400/mês" in retorno


def test_metragem_sai_sem_casa_decimal(catalogo, lead_id, deps):
    """`Decimal` com escala 2 imprime "500.00m2" mesmo com :g."""
    retorno = _buscar({"tipo": "galpao"}, lead_id, deps)

    assert "780m²" in retorno
    assert "780.00m²" not in retorno


def test_filtro_contraditorio_vira_pedido_de_correcao(catalogo, lead_id, deps):
    """Nem tipo nem finalidade são afrouxados: sem isto, zero para sempre."""
    retorno = _buscar(
        {"tipo": "galpao", "finalidade": "residencial"}, lead_id, deps
    )

    assert "sempre comercial" in retorno


# --- Operação: uma por busca -------------------------------------------------


def test_sem_operacao_a_lista_mista_vem_com_aviso(catalogo, lead_id, deps):
    """Ordenada por preço, a lista mista esconde as vendas atrás dos aluguéis."""
    retorno = _buscar({}, lead_id, deps)

    assert "mistura venda e aluguel" in retorno
    assert "uma busca para cada uma" in retorno


def test_com_operacao_nao_ha_aviso(catalogo, lead_id, deps):
    retorno = _buscar({"operacao": "venda"}, lead_id, deps)

    assert "mistura venda e aluguel" not in retorno


def test_a_operacao_sai_da_intencao_ja_registrada_do_lead(catalogo, lead_id, deps, db):
    """O modelo não precisa repetir numa tool o que já gravou noutra."""
    LeadService().update_qualification(lead_id, {"intencao": "aluguel"}, db)

    retorno = _buscar({}, lead_id, deps)

    assert "mistura venda e aluguel" not in retorno
    assert "Apartamento Bela Vista Compacto" not in retorno  # é venda
