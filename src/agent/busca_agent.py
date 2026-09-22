"""Recuperação de imóveis do catálogo.

Quem conversa com o cliente é a Marina; quem procura imóvel é este agente. Ela
descreve o que a pessoa quer em texto livre, ele consulta o catálogo por SQL
quantas vezes precisar e devolve os IDs escolhidos com uma linha de porquê para
cada um.

A separação resolve duas exigências que puxam em direções opostas (ADR 0007). O
que a pessoa diz raramente se traduz em filtros sem perda, e o contrato que
aceitaria tudo isso em campos tipados pesaria em toda requisição do agente
conversacional — inclusive nos turnos em que ninguém busca nada. Aqui as
instruções longas de busca só são lidas quando há busca.

Ele devolve IDs e julgamento, nunca números. Preço, metragem e cômodos são
relidos do banco por quem chama. O julgamento é do agente; os números são do
PostgreSQL.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from src.agent.prompts import BUSCA_SYSTEM_PROMPT
from src.agent.provider import build_model_busca
from src.db.session import get_db
from src.services.catalog_service import (
    PERFIS_INDICADOS,
    TIPOS,
    ZONAS,
    CatalogService,
)
from src.services.consulta_catalogo import ConsultaRecusada, executar

logger = logging.getLogger(__name__)

# Teto de idas ao provider por busca. Cada uma é uma consulta ao catálogo mais
# o raciocínio em cima do que veio; quatro cobrem "tentei, não achei, entendi
# por quê, tentei de novo". Sem teto, um modelo indeciso ficaria refinando a
# consulta enquanto alguém espera resposta no WhatsApp.
LIMITE_DE_REQUISICOES = 5


class ImovelEscolhido(BaseModel):
    """Um imóvel selecionado, com a razão de ter sido."""

    imovel_id: Annotated[int, Field(description=(
        "O `id` do imóvel, exatamente como veio na consulta."))]
    porque: Annotated[str, Field(max_length=200, description=(
        "Uma linha dizendo por que ESTE imóvel serve para ESTA pessoa, com o "
        "dado concreto que sustenta isso. Não escreva elogio genérico."))]


class Recomendacao(BaseModel):
    """O que a busca concluiu."""

    escolhidos: Annotated[list[ImovelEscolhido], Field(description=(
        "De 3 a 5 imóveis, do mais aderente ao menos. Vazio quando o catálogo "
        "não tem o que foi pedido — nesse caso a `observacao` explica."))]
    observacao: Annotated[str, Field(max_length=600, description=(
        "O que precisou ser afrouxado em relação ao pedido, ou o que o "
        "catálogo tem de verdade quando não há nada. Vazia quando o pedido foi "
        "atendido como veio."))] = ""


@dataclass
class BuscaDeps:
    """Contexto de uma busca, e o rastro que ela vai deixando."""

    correlation_id: Optional[str] = None
    # Preenchido pela tool a cada consulta, na ordem em que aconteceram. É o
    # que vai para observabilidade: as consultas intermediárias não entram no
    # histórico da conversa, então sem isto não há como reconstruir depois como
    # o agente chegou aos imóveis que escolheu.
    consultas: list[str] = field(default_factory=list)


@dataclass
class ResultadoDaBusca:
    """O que a busca devolve a quem a chamou, com o custo da chamada."""

    escolhidos: list[ImovelEscolhido]
    observacao: str
    consultas: list[str]
    tokens_in: int
    tokens_out: int

    @property
    def ids(self) -> list[int]:
        return [escolhido.imovel_id for escolhido in self.escolhidos]


busca_agent = Agent(
    deps_type=BuscaDeps,
    output_type=Recomendacao,
    system_prompt=BUSCA_SYSTEM_PROMPT.format(
        tipos=", ".join(TIPOS),
        zonas=", ".join(ZONAS),
        perfis=", ".join(PERFIS_INDICADOS),
    ),
    retries=2,
)


@busca_agent.instructions
def amenidades_do_catalogo() -> str:
    """As amenidades mais frequentes, lidas do banco a cada busca.

    Vão nas instruções, e não no prompt fixo, porque são dado e não regra: uma
    lista escrita à mão envelheceria na primeira carga de catálogo nova. É o
    mesmo motivo pelo qual tipos, zonas e perfis vêm das constantes que os
    testes comparam com o `SELECT DISTINCT` das colunas.

    Sem cache de propósito. A consulta é um `GROUP BY` sobre algumas centenas
    de linhas, insignificante ao lado dos segundos que a busca leva no
    provider — e um cache de processo congelaria o vocabulário do primeiro
    catálogo que fosse visto.
    """
    with get_db() as db:
        etiquetas = CatalogService().vocabulario_de_tags(db)
    if not etiquetas:
        return ""
    return (
        "## Amenidades mais frequentes agora, com quantos imóveis as têm\n"
        + ", ".join(etiquetas)
        + "\n\nÉ o vocabulário que os anúncios usam. Traduza o pedido da "
        "pessoa para ele antes de procurar."
    )


@busca_agent.tool
async def consultar(
    ctx: RunContext[BuscaDeps],
    sql: Annotated[str, Field(description=(
        "Um `SELECT` sobre a tabela `imoveis`. Um comando só, sem ponto e "
        "vírgula no meio e sem comentário."))],
) -> str:
    """Executar uma consulta de leitura no catálogo.

    Devolve as linhas em texto. Consulta recusada ou com erro volta com a
    explicação, para você reescrever — errar aqui não custa nada além de uma
    tentativa.
    """
    try:
        resultado = executar(sql, correlation_id=ctx.deps.correlation_id)
    except ConsultaRecusada as e:
        ctx.deps.consultas.append(f"[{e.motivo}] {sql}")
        # `ModelRetry` e não retorno de texto: é o pydantic-ai que controla
        # quantas vezes ele pode insistir, e uma recusa devolvida como
        # resultado normal deixaria o agente tentar para sempre.
        raise ModelRetry(str(e)) from e

    ctx.deps.consultas.append(resultado.sql_executado)
    return resultado.para_texto()


def build_busca_prompt(
    pedido: str,
    contexto_do_lead: str,
    perfil_narrativo: Optional[str],
    ja_mostrados: list[int],
) -> str:
    """Monta o pedido da busca com o que se sabe da pessoa.

    A ficha e o perfil entram para desempatar o que o pedido não diz: entre
    dois imóveis igualmente aderentes, o que já se sabe dela decide. Não são
    filtros — o pedido é que manda, inclusive quando contradiz a ficha, porque
    a pessoa acabou de mudar de ideia com mais frequência do que a ficha foi
    atualizada.
    """
    partes = [f"## O que a pessoa procura agora\n{pedido.strip()}"]

    contexto = (contexto_do_lead or "").strip()
    if contexto:
        partes.append(
            "## Ficha do lead\n"
            "Use para desempatar, não como filtro: o pedido acima é que manda.\n"
            f"{contexto}"
        )

    perfil = (perfil_narrativo or "").strip()
    if perfil:
        partes.append(
            "## Perfil narrativo\n"
            "O que a conversa revelou até aqui, inclusive o que ela já "
            f"recusou e por quê.\n{perfil}"
        )

    if ja_mostrados:
        partes.append(
            "## Já apresentados nesta conversa\n"
            f"IDs {', '.join(str(i) for i in ja_mostrados)}.\n"
            "Não os ofereça de novo como novidade: exclua-os na consulta. A "
            "exceção é quando o pedido acima for sobre um deles."
        )

    partes.append("Busque agora e devolva os imóveis escolhidos.")
    return "\n\n".join(partes)


async def buscar(
    pedido: str,
    contexto_do_lead: str = "",
    perfil_narrativo: Optional[str] = None,
    ja_mostrados: Optional[list[int]] = None,
    correlation_id: Optional[str] = None,
) -> ResultadoDaBusca:
    """Procura no catálogo e devolve os imóveis escolhidos.

    Levanta exceção quando o provider falha ou quando o agente estoura o teto
    de requisições — quem chama degrada para a busca estruturada, que não
    depende de LLM nenhum.
    """
    deps = BuscaDeps(correlation_id=correlation_id)
    comeco = time.monotonic()

    resultado = await busca_agent.run(
        user_prompt=build_busca_prompt(
            pedido, contexto_do_lead, perfil_narrativo, ja_mostrados or []
        ),
        deps=deps,
        model=build_model_busca(),
        usage_limits=UsageLimits(request_limit=LIMITE_DE_REQUISICOES),
    )

    recomendacao = resultado.output
    usage = resultado.usage

    logger.info(
        "event=busca_concluida correlation_id=%s consultas=%s escolhidos=%s "
        "duracao_ms=%s",
        correlation_id, len(deps.consultas), len(recomendacao.escolhidos),
        int((time.monotonic() - comeco) * 1000),
    )

    return ResultadoDaBusca(
        escolhidos=recomendacao.escolhidos,
        observacao=recomendacao.observacao,
        consultas=deps.consultas,
        tokens_in=usage.input_tokens or 0,
        tokens_out=usage.output_tokens or 0,
    )
