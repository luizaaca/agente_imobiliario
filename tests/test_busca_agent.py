"""O agente que recupera imóveis, e o que ele não repete.

O modelo é falso em todos os testes; o banco é de verdade. É a combinação que
interessa: o que se quer verificar é que a tool executa SQL de verdade, que a
recusa volta para o agente como retentativa e que o rastro sobrevive — nada
disso depende de qual modelo está do outro lado.
"""

import asyncio
import time

import pytest
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimitExceeded

from src.agent import busca_agent as busca_mod
from src.agent import imoveis_mostrados
from src.agent.busca_agent import (
    LIMITE_DE_REQUISICOES,
    build_busca_prompt,
    buscar,
)
from src.services.catalog_service import PERFIS_INDICADOS, TIPOS, ZONAS


def _consulta(sql: str) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name="consultar", args={"sql": sql})]
    )


def _resposta(escolhidos, observacao: str = "") -> ModelResponse:
    """A saída estruturada do agente, que o pydantic-ai entrega por tool."""
    return ModelResponse(
        parts=[ToolCallPart(
            tool_name="final_result",
            args={
                "escolhidos": [
                    {"imovel_id": id_, "porque": porque}
                    for id_, porque in escolhidos
                ],
                "observacao": observacao,
            },
        )]
    )


def modelo_de_busca(*respostas):
    """FunctionModel que devolve as respostas na ordem, repetindo a última."""
    passo = {"n": 0}

    def responder(messages, info):
        resposta = respostas[min(passo["n"], len(respostas) - 1)]
        passo["n"] += 1
        return resposta

    return FunctionModel(responder)


def rodar(*respostas, **kwargs):
    """Executa uma busca com o modelo simulado."""
    async def principal():
        with busca_mod.busca_agent.override(model=modelo_de_busca(*respostas)):
            return await buscar(**kwargs)

    return asyncio.run(principal())


# --- A busca de ponta a ponta ------------------------------------------------

def test_busca_consulta_o_catalogo_e_devolve_os_escolhidos(catalogo):
    resultado = rodar(
        _consulta("SELECT id, titulo, preco FROM imoveis WHERE operacao = 'venda'"),
        _resposta([(1, "2 quartos na Bela Vista, dentro do orçamento")]),
        pedido="apartamento de 2 quartos até 600 mil",
    )

    assert resultado.ids == [1]
    assert resultado.escolhidos[0].porque.startswith("2 quartos")
    assert resultado.consultas == [
        "SELECT id, titulo, preco FROM imoveis WHERE operacao = 'venda' LIMIT 100"
    ]


def test_o_rastro_guarda_o_sql_como_foi_executado(catalogo):
    """O LIMIT acrescentado tem que aparecer no rastro, e não o SQL original.

    As consultas intermediárias não entram no histórico da conversa; se o
    rastro guardar o que o modelo pediu em vez do que rodou, não há como
    reconstruir depois de onde saíram os imóveis.
    """
    resultado = rodar(
        _consulta("SELECT id FROM imoveis"),
        _resposta([(1, "primeiro da lista")]),
        pedido="qualquer coisa",
    )
    assert resultado.consultas == ["SELECT id FROM imoveis LIMIT 100"]


def test_consulta_recusada_volta_para_o_agente_reescrever(catalogo):
    """A recusa é retentativa, não falha da busca.

    Errar a consulta custa uma tentativa e nada mais — é para isso que a
    mensagem de recusa explica o que houve.
    """
    resultado = rodar(
        _consulta("SELECT nome, telefone FROM leads"),
        _consulta("SELECT id, titulo FROM imoveis LIMIT 3"),
        _resposta([(2, "segunda opção na mesma rua")]),
        pedido="apartamento na Bela Vista",
    )

    assert resultado.ids == [2]
    assert resultado.consultas[0].startswith("[guarda]")
    assert "leads" in resultado.consultas[0]
    assert resultado.consultas[1] == "SELECT id, titulo FROM imoveis LIMIT 3"


def test_erro_do_postgres_tambem_volta_como_retentativa(catalogo):
    resultado = rodar(
        _consulta("SELECT coluna_inexistente FROM imoveis"),
        _consulta("SELECT id FROM imoveis LIMIT 2"),
        _resposta([(1, "serve")]),
        pedido="qualquer coisa",
    )
    assert resultado.consultas[0].startswith("[sql]")
    assert resultado.ids == [1]


def test_observacao_atravessa_a_busca(catalogo):
    resultado = rodar(
        _consulta("SELECT id FROM imoveis WHERE bairro ILIKE '%Moema%'"),
        _resposta([(3, "única cobertura")], observacao="Não havia em Pinheiros; ampliei para a zona sul."),
        pedido="cobertura em Pinheiros",
    )
    assert "ampliei" in resultado.observacao


def test_lista_vazia_e_resposta_valida(catalogo):
    """Sem imóvel, a observação é o que resta — e ela não pode se perder."""
    resultado = rodar(
        _consulta("SELECT count(*) FROM imoveis WHERE tipo = 'galpao'"),
        _resposta([], observacao="Há 1 galpão, e é para alugar, não à venda."),
        pedido="galpão à venda",
    )
    assert resultado.escolhidos == []
    assert "galpão" in resultado.observacao


def test_o_custo_da_busca_volta_para_quem_chamou(catalogo):
    """Sem isto, o consumo do agente de busca não entra em `llm_usage`."""
    resultado = rodar(
        _consulta("SELECT id FROM imoveis LIMIT 1"),
        _resposta([(1, "serve")]),
        pedido="qualquer coisa",
    )
    assert resultado.tokens_in > 0
    assert resultado.tokens_out > 0


def test_agente_indeciso_esbarra_no_nosso_teto_de_requisicoes(catalogo):
    """Sem teto, ele refinaria a consulta enquanto alguém espera resposta.

    A contagem de chamadas é o que importa aqui. O pydantic-ai já traz um teto
    próprio de 50 requisições, e só verificar que a exceção subiu não
    distinguiria o nosso limite do padrão dele — 50 idas ao provider dentro de
    uma chamada de tool é exatamente o que este teto existe para impedir.
    """
    chamadas = []

    def responder(messages, info):
        chamadas.append(1)
        return _consulta("SELECT id FROM imoveis LIMIT 1")

    async def principal():
        with busca_mod.busca_agent.override(model=FunctionModel(responder)):
            return await buscar(pedido="qualquer coisa")

    with pytest.raises(UsageLimitExceeded):
        asyncio.run(principal())

    assert len(chamadas) <= LIMITE_DE_REQUISICOES


def test_consulta_sempre_recusada_encerra_em_vez_de_insistir(catalogo):
    """Errar custa uma tentativa; errar sempre não pode virar laço.

    A recusa sobe como `ModelRetry`, então quem conta as tentativas é a
    política de retentativa do pydantic-ai. Devolvê-la como resultado normal
    deixaria o agente reenviar a mesma consulta proibida até esbarrar no teto
    de requisições, gastando o orçamento inteiro da busca em recusas.
    """
    with pytest.raises(UnexpectedModelBehavior):
        rodar(_consulta("SELECT nome FROM leads"), pedido="qualquer coisa")


def test_o_teto_permite_investigar_antes_de_responder(catalogo):
    """Tentar, não achar, entender por quê e tentar de novo tem que caber."""
    resultado = rodar(
        _consulta("SELECT id FROM imoveis WHERE preco < 100"),
        _consulta("SELECT count(*), min(preco) FROM imoveis"),
        _consulta("SELECT id FROM imoveis ORDER BY preco LIMIT 3"),
        _resposta([(4, "o mais barato do catálogo")]),
        pedido="algo bem barato",
    )
    assert len(resultado.consultas) == 3
    assert len(resultado.consultas) < LIMITE_DE_REQUISICOES


# --- O prompt da busca -------------------------------------------------------

def test_prompt_traz_o_pedido_a_ficha_e_o_perfil():
    prompt = build_busca_prompt(
        "apartamento perto do metrô",
        "Nome: Ana\nOrçamento: até R$ 600.000",
        "Recusou o primeiro imóvel pela cozinha pequena.",
        [],
    )
    assert "apartamento perto do metrô" in prompt
    assert "Orçamento: até R$ 600.000" in prompt
    assert "cozinha pequena" in prompt
    assert "Já apresentados" not in prompt


def test_prompt_lista_os_ja_apresentados_quando_ha():
    prompt = build_busca_prompt("outro parecido", "", None, [7, 12])
    assert "7, 12" in prompt
    assert "novidade" in prompt


def test_prompt_omite_secoes_vazias():
    """Cabeçalho sem conteúdo é ruído que o modelo tenta interpretar."""
    prompt = build_busca_prompt("apartamento", "", None, [])
    assert "Ficha do lead" not in prompt
    assert "Perfil narrativo" not in prompt


def test_instrucoes_usam_o_vocabulario_real_do_catalogo():
    """O prompt não pode envelhecer em silêncio quando o catálogo muda.

    As listas vêm das mesmas constantes que `test_catalog_service.py` compara
    com o `SELECT DISTINCT` das colunas — então um tipo novo no banco chega
    aqui sem ninguém precisar lembrar.
    """
    instrucoes = busca_mod.busca_agent._system_prompts[0]
    for valor in (*TIPOS, *ZONAS, *PERFIS_INDICADOS):
        assert valor in instrucoes


# --- Imóveis já apresentados -------------------------------------------------

@pytest.fixture(autouse=True)
def cache_limpo():
    imoveis_mostrados._por_lead.clear()
    yield
    imoveis_mostrados._por_lead.clear()


def test_acumula_entre_buscas_sem_repetir():
    imoveis_mostrados.registrar(1, [10, 20])
    imoveis_mostrados.registrar(1, [20, 30])
    assert imoveis_mostrados.ja_mostrados(1) == [10, 20, 30]


def test_leads_diferentes_nao_se_misturam():
    imoveis_mostrados.registrar(1, [10])
    imoveis_mostrados.registrar(2, [20])
    assert imoveis_mostrados.ja_mostrados(1) == [10]
    assert imoveis_mostrados.ja_mostrados(2) == [20]


def test_lead_sem_busca_nao_tem_nada():
    assert imoveis_mostrados.ja_mostrados(999) == []


def test_o_teto_descarta_os_mais_antigos():
    """Lembrar demais estreita o catálogo até não sobrar o que mostrar."""
    imoveis_mostrados.registrar(1, list(range(100)))
    lembrados = imoveis_mostrados.ja_mostrados(1)
    assert len(lembrados) == imoveis_mostrados.TETO_POR_LEAD
    assert lembrados[-1] == 99
    assert 0 not in lembrados


def test_esquece_depois_da_validade(monkeypatch):
    imoveis_mostrados.registrar(1, [10])
    depois = time.monotonic() + imoveis_mostrados.VALIDADE_EM_SEGUNDOS + 1
    monkeypatch.setattr(imoveis_mostrados.time, "monotonic", lambda: depois)
    assert imoveis_mostrados.ja_mostrados(1) == []


def test_nova_apresentacao_renova_a_validade(monkeypatch):
    """Uma conversa longa com atividade o tempo todo não esquece no meio."""
    imoveis_mostrados.registrar(1, [10])

    quase = time.monotonic() + imoveis_mostrados.VALIDADE_EM_SEGUNDOS - 1
    monkeypatch.setattr(imoveis_mostrados.time, "monotonic", lambda: quase)
    imoveis_mostrados.registrar(1, [20])

    bem_depois = quase + imoveis_mostrados.VALIDADE_EM_SEGUNDOS - 1
    monkeypatch.setattr(imoveis_mostrados.time, "monotonic", lambda: bem_depois)
    assert imoveis_mostrados.ja_mostrados(1) == [10, 20]


def test_escrita_descarta_conversas_vencidas_de_outros_leads(monkeypatch):
    """Um processo dias no ar não deve segurar conversa nenhuma na memória."""
    imoveis_mostrados.registrar(1, [10])
    depois = time.monotonic() + imoveis_mostrados.VALIDADE_EM_SEGUNDOS + 1
    monkeypatch.setattr(imoveis_mostrados.time, "monotonic", lambda: depois)

    imoveis_mostrados.registrar(2, [20])
    assert 1 not in imoveis_mostrados._por_lead


def test_esquecer_zera_a_conversa():
    imoveis_mostrados.registrar(1, [10])
    imoveis_mostrados.esquecer(1)
    assert imoveis_mostrados.ja_mostrados(1) == []


# --- O vocabulário do catálogo -----------------------------------------------

def test_as_amenidades_do_catalogo_chegam_as_instrucoes(catalogo):
    """Sem elas, ele conclui que "varanda gourmet" não existe.

    As palavras do anúncio raramente são as da pessoa: quem pede varanda
    gourmet quer o que o catálogo cadastrou como `churrasqueira`. Conhecer o
    vocabulário é o que permite traduzir um pelo outro.
    """
    visto = {}

    def espiar(messages, info):
        visto["instrucoes"] = info.instructions or ""
        return _resposta([(1, "serve")])

    async def principal():
        with busca_mod.busca_agent.override(model=FunctionModel(espiar)):
            return await buscar(pedido="apartamento com churrasqueira")

    asyncio.run(principal())

    # A frequência vai junto: é ela que diz qual palavra o catálogo prefere.
    assert "metro (3)" in visto["instrucoes"]
    assert "varanda gourmet (2)" in visto["instrucoes"]


def test_o_vocabulario_vem_do_banco_e_nao_de_uma_lista_fixa(catalogo, db):
    """Uma lista escrita à mão envelhece na primeira carga de catálogo nova."""
    from src.db.models import Imovel

    db.query(Imovel).update({Imovel.tags: "heliponto_exclusivo"})
    db.commit()

    visto = {}

    def espiar(messages, info):
        visto["instrucoes"] = info.instructions or ""
        return _resposta([(1, "serve")])

    async def principal():
        with busca_mod.busca_agent.override(model=FunctionModel(espiar)):
            return await buscar(pedido="qualquer coisa")

    asyncio.run(principal())

    assert "heliponto_exclusivo" in visto["instrucoes"]
    assert "varanda gourmet" not in visto["instrucoes"]


def test_catalogo_vazio_nao_inventa_secao_de_amenidades():
    """Cabeçalho sem conteúdo é ruído que o modelo tenta interpretar."""
    assert busca_mod.amenidades_do_catalogo() == ""


# --- Completar a lista com o que nao serve ----------------------------------

def test_lista_que_mistura_residencial_e_comercial_volta_para_o_agente(catalogo):
    """Numa busca real por casa de aluguel, tres de cinco eram comerciais.

    O catalogo tem uma casa so na zona leste para alugar, e o agente completou
    a cota com predio comercial de R$ 38 mil e andar corporativo. A Marina nao
    podia mostrar nenhum deles.
    """
    modelo = modelo_de_busca(
        _resposta([(1, "apartamento na Bela Vista"), (6, "sala comercial")]),
        _resposta([(1, "apartamento na Bela Vista")], "so um serve"),
    )

    with busca_mod.busca_agent.override(model=modelo):
        resultado = asyncio.run(buscar("apartamento para morar"))

    assert resultado.ids == [1]
    assert resultado.observacao == "so um serve"


def test_a_recusa_chega_ao_modelo_dizendo_o_que_fazer(catalogo):
    """Retentativa sem instrucao vira a mesma resposta de novo."""
    vistas = []

    def responder(messages, info):
        vistas.append(messages)
        if len(vistas) == 1:
            return _resposta([(1, "residencial"), (6, "comercial")])
        return _resposta([(1, "residencial")])

    with busca_mod.busca_agent.override(model=FunctionModel(responder)):
        asyncio.run(buscar("apartamento"))

    texto_da_retentativa = chr(10).join(
        str(parte.content)
        for mensagem in vistas[-1]
        for parte in mensagem.parts
        if hasattr(parte, "content")
    )
    assert "residencial e comercial" in texto_da_retentativa
    assert "devolver menos" in texto_da_retentativa


def test_lista_de_uma_finalidade_so_passa_direto(catalogo):
    """O guard nao pode atrapalhar a busca correta."""
    modelo = modelo_de_busca(
        _resposta([(1, "compacto"), (2, "vista livre"), (3, "cobertura")])
    )

    with busca_mod.busca_agent.override(model=modelo):
        resultado = asyncio.run(buscar("apartamento na zona sul"))

    assert resultado.ids == [1, 2, 3]


def test_um_imovel_so_nunca_e_recusado(catalogo):
    """Devolver um quando so um serve e exatamente o comportamento pedido."""
    modelo = modelo_de_busca(
        _resposta([(6, "a unica sala comercial que serve")], "o catalogo tem uma so")
    )

    with busca_mod.busca_agent.override(model=modelo):
        resultado = asyncio.run(buscar("sala comercial para alugar"))

    assert resultado.ids == [6]
