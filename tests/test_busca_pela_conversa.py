"""A tool de busca vista de fora: o que a Marina manda e o que ela recebe.

Os testes do `CatalogService` cobrem o SQL, e os de `test_busca_agent.py`
cobrem quem decide o que mostrar. Estes cobrem a costura entre os dois — o
schema que a Marina preenche, os números que voltam e o que sobra registrado —
porque foi na costura que os defeitos reais apareceram: a pessoa pediu galpão e
recebeu sala comercial, e o imóvel já mostrado voltou como novidade.
"""

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from src.agent import sdr_agent as agent_mod
from src.agent.history import (
    HISTORY_LIMIT,
    LIMITE_DO_RETORNO_DE_TOOL,
    build_message_history,
)
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.models import LLMUsage, Mensagem
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

from .conftest import consulta_do_catalogo, escolha_da_busca


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


def _turno_com_busca(pedido, lead_id, deps) -> str:
    """Roda um turno em que a Marina chama a busca e devolve o que a tool disse."""
    capturado = {}

    def modelo(messages, info):
        if not capturado:
            capturado["chamou"] = True
            return ModelResponse(parts=[ToolCallPart(
                tool_name="buscar_imoveis", args={"pedido": pedido}
            )])
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


# --- O que a Marina vê -------------------------------------------------------


def test_a_busca_pede_um_campo_so(lead_id, deps):
    """O contrato de dezenove filtros pesava em toda requisição de todo turno.

    Descrever bem cada filtro — que é o que a expressividade pedia — encarecia
    os turnos sem busca para melhorar os com busca. Um campo de texto livre
    tira esse detalhe do caminho de quem conversa.
    """
    schema = _schema(lead_id, deps)

    assert list(schema["properties"]) == ["pedido"]
    assert schema["required"] == ["pedido"]


def test_o_campo_da_busca_e_descrito(lead_id, deps):
    """Descrição de parâmetro é o que mais muda o acerto de uma tool."""
    pedido = _schema(lead_id, deps)["properties"]["pedido"]

    assert pedido.get("description")
    assert "palavras dela" in pedido["description"]


def test_o_schema_da_busca_e_barato(lead_id, deps):
    """Ele é reenviado em toda requisição, inclusive nos turnos sem busca."""
    import json

    tamanho = len(json.dumps(_schema(lead_id, deps), ensure_ascii=False))
    assert tamanho < 1000


# --- Os números vêm do banco -------------------------------------------------


def test_o_imovel_escolhido_vira_ficha_com_os_dados_do_catalogo(
    catalogo, lead_id, deps, busca_fake
):
    with busca_fake(
        consulta_do_catalogo("SELECT id FROM imoveis WHERE tipo = 'galpao'"),
        escolha_da_busca((7, "780m² com doca, é o único galpão")),
    ):
        retorno = _turno_com_busca("galpão para logística", lead_id, deps)

    assert "Galpao Belem Logistico" in retorno
    assert "780m² com doca" in retorno


def test_o_preco_apresentado_e_o_do_banco_e_nao_o_que_o_modelo_disse(
    catalogo, lead_id, deps, busca_fake
):
    """O julgamento é do agente de busca; os números são do PostgreSQL.

    A persona promete à pessoa que nunca inventa preço, e essa promessa não
    sobrevive a número escrito por modelo. Aqui o agente de busca mente no
    `porque`, e o preço da ficha continua certo.
    """
    with busca_fake(escolha_da_busca((7, "sai por R$ 1.000, uma pechincha"))):
        retorno = _turno_com_busca("galpão barato", lead_id, deps)

    assert "R$ 18.000" in retorno
    assert "R$ 18,000" not in retorno


def test_aluguel_mostra_o_custo_total_do_mes(catalogo, lead_id, deps, busca_fake):
    with busca_fake(escolha_da_busca((6, "sala pronta para escritório"))):
        retorno = _turno_com_busca("sala comercial", lead_id, deps)

    assert "R$ 4.500 + condomínio R$ 900 = R$ 5.400/mês" in retorno


def test_metragem_sai_sem_casa_decimal(catalogo, lead_id, deps, busca_fake):
    """`Decimal` com escala 2 imprime "780.00m²" mesmo com :g."""
    with busca_fake(escolha_da_busca((7, "cabe a operação inteira"))):
        retorno = _turno_com_busca("galpão", lead_id, deps)

    assert "780m²" in retorno
    assert "780.00m²" not in retorno


def test_id_inventado_nao_vira_ficha(catalogo, lead_id, deps, busca_fake):
    """Ficha de imóvel que não existe é a pior saída possível.

    O ID vai para `agendar_reuniao` e de lá para a agenda do corretor: um
    número inventado poria uma visita a um imóvel inexistente na agenda dele.
    """
    with busca_fake(escolha_da_busca(
        (7, "existe de verdade"), (9999, "fantasma inventado pelo modelo"),
    )):
        retorno = _turno_com_busca("galpão", lead_id, deps)

    assert "Galpao Belem Logistico" in retorno
    assert "9999" not in retorno
    assert "fantasma inventado" not in retorno


# --- A observação da busca ---------------------------------------------------


def test_o_que_foi_afrouxado_chega_a_marina(catalogo, lead_id, deps, busca_fake):
    """Sem as palavras do que mudou, ela inventa que ampliou sem ter ampliado."""
    with busca_fake(escolha_da_busca(
        (3, "a única cobertura do catálogo"),
        observacao="Não havia cobertura em Pinheiros; ampliei para a zona sul.",
    )):
        retorno = _turno_com_busca("cobertura em Pinheiros", lead_id, deps)

    assert "ampliei para a zona sul" in retorno


def test_a_observacao_vem_depois_das_fichas_e_rotulada(
    catalogo, lead_id, deps, busca_fake
):
    """A ordem em que o modelo lê é a ordem em que ele tende a escrever.

    Aconteceu numa conversa real: a busca anotou "não encontrei a combinação
    exata de varanda gourmet e metrô", a Marina abriu a mensagem por isso, e os
    três imóveis logo abaixo tinham churrasqueira E metrô. A pessoa leu uma
    recusa antes de ler o que servia para ela.
    """
    with busca_fake(escolha_da_busca(
        (7, "serve"), observacao="Não havia a combinação exata.",
    )):
        retorno = _turno_com_busca("galpão", lead_id, deps)

    assert retorno.index("Galpao Belem Logistico") < retorno.index(
        "Não havia a combinação exata"
    )
    assert "não para copiar" in retorno
    assert "Abra pelo que você TEM" in retorno


def test_catalogo_sem_nada_ainda_traz_os_numeros(
    catalogo, lead_id, deps, busca_fake
):
    """"Não achei" sozinho faz a Marina pedir desculpa no vazio."""
    with busca_fake(escolha_da_busca(
        observacao="O catálogo tem 1 galpão, e é para alugar, não à venda.",
    )):
        retorno = _turno_com_busca("galpão à venda", lead_id, deps)

    assert "1 galpão" in retorno


# --- O que não se repete -----------------------------------------------------


def test_o_imovel_ja_mostrado_vai_como_exclusao_na_busca_seguinte(
    catalogo, lead_id, deps, busca_fake
):
    """Numa conversa real ele reapresentou o mesmo apartamento como novidade."""
    with busca_fake(escolha_da_busca((7, "serve"))):
        _turno_com_busca("galpão", lead_id, deps)

    visto = {}

    def espiar(messages, info):
        visto["prompt"] = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if type(p).__name__ == "UserPromptPart"
        )
        return escolha_da_busca((6, "outra opção"))

    from src.agent import busca_agent as busca_mod
    with busca_mod.busca_agent.override(model=FunctionModel(espiar)):
        _turno_com_busca("mostre outro", lead_id, deps)

    assert "Já apresentados" in visto["prompt"]
    assert "7" in visto["prompt"]


def test_a_ficha_do_lead_chega_ao_agente_de_busca(
    catalogo, lead_id, deps, busca_fake, db
):
    """O que já se sabe dela desempata o que o pedido não diz."""
    LeadService().update_qualification(
        lead_id, {"intencao": "aluguel", "orcamento_max": 5000}, db
    )

    visto = {}

    def espiar(messages, info):
        visto["prompt"] = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if type(p).__name__ == "UserPromptPart"
        )
        return escolha_da_busca((6, "cabe no orçamento"))

    from src.agent import busca_agent as busca_mod
    with busca_mod.busca_agent.override(model=FunctionModel(espiar)):
        _turno_com_busca("algo para a empresa", lead_id, deps)

    assert "Quer: aluguel" in visto["prompt"]
    assert "5.000" in visto["prompt"]


def test_a_agenda_do_lead_nao_vai_para_o_agente_de_busca(
    catalogo, lead_id, deps, busca_fake
):
    """Compromisso e estágio no funil são assunto de quem conversa.

    No contexto de quem procura imóvel seriam tokens gastos em nada, e a busca
    roda dentro do turno — o que ela gasta, a pessoa espera.
    """
    visto = {}

    def espiar(messages, info):
        visto["prompt"] = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if type(p).__name__ == "UserPromptPart"
        )
        return escolha_da_busca((7, "serve"))

    from src.agent import busca_agent as busca_mod
    with busca_mod.busca_agent.override(model=FunctionModel(espiar)):
        _turno_com_busca("galpão", lead_id, deps)

    assert "Compromissos marcados" not in visto["prompt"]
    assert "Estágio no funil" not in visto["prompt"]


# --- Quando o provider cai ---------------------------------------------------


def test_provider_fora_do_ar_ainda_devolve_imoveis(
    catalogo, lead_id, deps, busca_fora_do_ar, db
):
    """A busca degrada em qualidade, não em disponibilidade.

    A pessoa está esperando imóvel na tela; um pedido de desculpas porque uma
    chamada caiu é o pior resultado possível quando o catálogo está de pé.
    """
    LeadService().update_qualification(lead_id, {"intencao": "aluguel"}, db)

    with busca_fora_do_ar():
        retorno = _turno_com_busca("algo para alugar na zona leste", lead_id, deps)

    # Fichas de verdade, com ID — é o que `agendar_reuniao` vai precisar.
    assert "(ID: " in retorno
    assert "Nenhum imóvel encontrado" not in retorno


def test_a_degradacao_usa_a_intencao_ja_gravada_do_lead(
    catalogo, lead_id, deps, busca_fora_do_ar, db
):
    """Sem LLM para ler o pedido, quem restringe é o que ela já informou."""
    LeadService().update_qualification(lead_id, {"intencao": "aluguel"}, db)

    with busca_fora_do_ar():
        retorno = _turno_com_busca("qualquer coisa", lead_id, deps)

    assert "Apartamento Bela Vista Compacto" not in retorno  # é venda


def test_a_falha_da_busca_e_registrada_como_erro(
    catalogo, lead_id, deps, busca_fora_do_ar, db
):
    """Falha que só existe no log não entra na taxa de erro do dashboard."""
    with busca_fora_do_ar():
        _turno_com_busca("qualquer coisa", lead_id, deps)

    linha = db.query(LLMUsage).filter(LLMUsage.operation == "busca").one()
    assert linha.status == "erro"
    assert linha.tokens_total == 0


# --- Observabilidade ---------------------------------------------------------


def test_o_custo_da_busca_e_separado_do_custo_de_conversar(
    catalogo, lead_id, deps, busca_fake, db
):
    """`operation="busca"` é o que torna a recuperação mensurável.

    Os tokens entram no orçamento do lead, mas não contam como turno de
    conversa: os agentes auxiliares trabalham dentro de um turno, não no lugar
    dele.
    """
    with busca_fake(escolha_da_busca((7, "serve"))):
        _turno_com_busca("galpão", lead_id, deps)

    busca = db.query(LLMUsage).filter(LLMUsage.operation == "busca").one()
    assert busca.tokens_total > 0
    assert busca.status == "ok"

    assert LLMUsageService().get_conversation_turns(lead_id, db) == 1


def test_as_consultas_ficam_no_rastro_da_mensagem(
    catalogo, lead_id, deps, busca_fake, db
):
    """As consultas não viram mensagem — este é o único registro delas.

    Sem isto não há como reconstruir depois de onde saíram os imóveis que a
    pessoa viu, que é justamente o que a delegação torna invisível.
    """
    with busca_fake(
        consulta_do_catalogo("SELECT id FROM imoveis WHERE tipo = 'galpao'"),
        escolha_da_busca((7, "serve")),
    ):
        _turno_com_busca("galpão", lead_id, deps)

    linha = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.role == "tool"
    ).one()

    rastro = linha.metadata_json["busca"]
    assert rastro["consultas"] == [
        "SELECT id FROM imoveis WHERE tipo = 'galpao' LIMIT 100"
    ]
    assert rastro["tokens_in"] > 0


def test_a_chamada_fica_gravada_com_o_pedido(
    catalogo, lead_id, deps, busca_fake, db
):
    """Saber o que ela buscou, e não só o que achou, é o que evita repetir."""
    with busca_fake(escolha_da_busca((7, "serve"))):
        _turno_com_busca("galpão com doca na zona leste", lead_id, deps)

    linha = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.role == "tool"
    ).one()

    assert linha.metadata_json["tool_name"] == "buscar_imoveis"
    assert linha.metadata_json["args"]["pedido"] == "galpão com doca na zona leste"


def test_o_imovel_mostrado_volta_no_historico_do_turno_seguinte(
    catalogo, lead_id, deps, busca_fake, db
):
    """Os IDs só existem no retorno da busca: ela nunca os escreve à pessoa.

    Sem persistir o retorno, `agendar_reuniao` fica sem `imovel_id` e o
    corretor recebe um horário sem saber aonde ir.
    """
    with busca_fake(escolha_da_busca((7, "serve"))):
        _turno_com_busca("galpão", lead_id, deps)

    historico = build_message_history(
        LeadService().get_history(lead_id, HISTORY_LIMIT, db)
    )
    tudo = "".join(
        str(getattr(p, "content", "")) for msg in historico for p in msg.parts
    )
    assert "Galpao Belem Logistico" in tudo
    assert "ID: 7" in tudo


def test_o_banco_guarda_o_retorno_inteiro(
    catalogo, lead_id, deps, busca_fake, db
):
    """Abreviar é coisa do histórico; a ficha do corretor fica com tudo."""
    with busca_fake(escolha_da_busca(
        (1, "primeira"), (2, "segunda"), (3, "terceira"), (4, "quarta"),
    )):
        _turno_com_busca("apartamentos à venda", lead_id, deps)

    linha = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.role == "tool"
    ).one()

    assert len(linha.content) > LIMITE_DO_RETORNO_DE_TOOL
