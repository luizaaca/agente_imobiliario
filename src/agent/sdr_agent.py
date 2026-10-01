"""Agente SDR Imobiliário principal usando PydanticAI."""

import functools
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from src.agent import imoveis_mostrados
from src.agent.busca_agent import buscar
from src.agent.history import HISTORY_LIMIT, build_message_history
from src.agent.perfil_agent import consolidar_perfil, juntar_sem_llm
from src.agent.prompts import HANDOVER_MESSAGE, SYSTEM_PROMPT, UNAVAILABLE_MESSAGE
from src.agent.provider import LLMConfigError, build_model, modelo_da_busca
from src.config import settings
from src.db.session import get_db
from src.services.catalog_service import (
    OPERACAO_POR_INTENCAO,
    CatalogService,
    FiltroInvalido,
    reais,
)
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import (
    CompromissoJaMarcado,
    SchedulingService,
)
from src.services.summary_service import SummaryService
from src.tempo import formatar, momento_atual, para_guardar

logger = logging.getLogger(__name__)


@dataclass
class SDRDependencies:
    """Dependências injetadas no agente."""
    lead_id: int
    channel: str
    lead_service: LeadService
    catalog_service: CatalogService
    scheduling_service: SchedulingService
    llm_usage_service: LLMUsageService
    # Amarra as linhas de log de um mesmo turno: a chamada ao provider e as
    # tools que ela disparou. Os canais constroem as dependências uma vez por
    # mensagem, então um id por objeto é um id por turno. Quem quiser correlacionar
    # com um id externo (um update do Telegram, por exemplo) passa o seu.
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Rastro das consultas de cada busca do turno, por `tool_call_id`. As
    # consultas do agente de busca não entram no histórico da conversa — é o
    # que torna a delegação barata —, então elas são recolhidas aqui e gravadas
    # no `metadata_json` da mensagem da ferramenta, para auditoria.
    rastros_de_busca: dict[str, dict] = field(default_factory=dict)


# Create the agent
# Nem o modelo nem o system prompt são fixados aqui:
# - o modelo vem de build_model() no momento do run, para que importar este
#   módulo não exija credenciais de LLM (o dashboard roda sem elas);
# - as instruções são montadas a cada run pelo @sdr_agent.instructions abaixo,
#   que injeta o contexto atual do lead no template.
sdr_agent = Agent(
    deps_type=SDRDependencies,
    retries=2,
)


def _decorrido_ms(comeco: float) -> int:
    """Milissegundos desde `comeco`, medidos em relógio monotônico."""
    return int((time.monotonic() - comeco) * 1000)


def _instrumentada(funcao):
    """Registra início, fim, duração e falha de uma tool.

    O `§8` dos contratos das tools pede `lead_id`, `tool_name`, `status`,
    duração, erro resumido e identificador de correlação em toda execução.
    Como isso é idêntico nas cinco tools, fica aqui em vez de repetido dentro
    de cada uma — e uma tool nova só precisa do decorador para ficar coberta.

    A exceção é relançada: o pydantic-ai tem a própria política de retentativa
    e é ele quem decide o que devolver ao modelo. Aqui só se observa.
    """
    nome = funcao.__name__

    @functools.wraps(funcao)
    async def wrapper(ctx: RunContext[SDRDependencies], *args, **kwargs):
        comeco = time.monotonic()
        logger.info(
            "event=tool_iniciada tool_name=%s lead_id=%s channel=%s correlation_id=%s",
            nome, ctx.deps.lead_id, ctx.deps.channel, ctx.deps.correlation_id,
        )
        try:
            resultado = await funcao(ctx, *args, **kwargs)
        except Exception as e:
            logger.exception(
                "event=tool_finalizada tool_name=%s lead_id=%s channel=%s "
                "correlation_id=%s status=erro tipo_erro=%s duracao_ms=%s",
                nome, ctx.deps.lead_id, ctx.deps.channel,
                ctx.deps.correlation_id, type(e).__name__, _decorrido_ms(comeco),
            )
            raise
        logger.info(
            "event=tool_finalizada tool_name=%s lead_id=%s channel=%s "
            "correlation_id=%s status=ok duracao_ms=%s",
            nome, ctx.deps.lead_id, ctx.deps.channel,
            ctx.deps.correlation_id, _decorrido_ms(comeco),
        )
        return resultado

    return wrapper


# Register tools using @sdr_agent.tool decorator
# Each tool receives RunContext[SDRDependencies] as first arg
#
# `@_instrumentada` fica por dentro de `@sdr_agent.tool`: o pydantic-ai lê a
# assinatura da função para montar o schema da tool, e `functools.wraps` deixa
# `inspect.signature` enxergar a original através do wrapper.

# Vai no fim do retorno da busca, e nao so no system prompt: o resultado da
# tool e o texto mais recente antes da geracao, e e ali que a instrucao pega.
#
# A regra de abrir pelo que existe nasceu de uma resposta real. A busca anotou
# "nao encontrei a combinacao exata de varanda gourmet e metro", o agente
# comecou a mensagem por isso, e os imoveis que ele mostrou logo abaixo
# tinham churrasqueira E metro — a pessoa leu uma recusa antes de ler o que
# servia para ela. O texto da busca descreve a BUSCA; a mensagem tem que
# descrever os IMOVEIS.
# A apresentacao so vale na primeira mensagem da conversa, e a regra enterrada
# no meio do prompt nao pegou: na primeira conversa de teste a Marina foi
# direto para a pergunta de descoberta. Como instrucao de runtime, ela e a
# ultima coisa que o modelo le antes de escrever — o mesmo motivo que fez o
# FECHAMENTO_DA_BUSCA funcionar.
#
# Nome e telefone se pedem aqui, e so o que falta: no Telegram o nome ja vem do
# perfil, e perguntar "como posso te chamar?" logo depois de "Oi, Luiz!" soaria
# como formulario.
ABERTURA_DA_CONVERSA = (
    "\n\n---\n"
    "ESTA É A SUA PRIMEIRA MENSAGEM DESTA CONVERSA. Abra como alguém da equipe "
    "abriria: um oi, seu nome e que você é da imobiliária, em uma linha. Não "
    "diga que é assistente virtual nem robô, e não explique o seu papel."
)

PEDIDO_DE_NOME_E_TELEFONE = (
    " Em seguida, numa frase só, pergunte como pode chamá-la e peça um "
    "telefone, dizendo para que serve: é por ele que o corretor fala com ela."
)
PEDIDO_DE_TELEFONE = (
    " O nome dela você já tem: chame por ele. Em seguida peça um telefone, "
    "dizendo para que serve: é por ele que o corretor fala com ela."
)
PEDIDO_DE_NOME = " Em seguida pergunte como pode chamá-la."
FECHO_DO_PEDIDO_DE_CONTATO = (
    " Peça sem obrigar, e sem anunciar que é opcional: se ela não der, a "
    "conversa segue igual. Nesta mensagem não pergunte o que ela procura; isso "
    "fica para a próxima.\n"
    "Releia a mensagem dela antes de escrever. Se ela trouxe qualquer coisa "
    "além de um cumprimento — o que procura, uma dúvida, um imóvel —, a sua "
    "mensagem tem que mostrar que ouviu, em meia linha, antes do pedido de "
    "contato. Ignorar o que ela disse para pedir telefone é o que um formulário "
    "faz."
)
SEM_PEDIDO_DE_CONTATO = (
    " Nome e telefone ela já deu: chame pelo nome e siga para a primeira "
    "pergunta."
)


def abertura_da_conversa(lead) -> str:
    """A ordem da primeira mensagem, pedindo só o contato que ainda falta."""
    tem_nome = bool(lead and lead.nome)
    tem_telefone = bool(lead and lead.telefone)
    if tem_nome and tem_telefone:
        return ABERTURA_DA_CONVERSA + SEM_PEDIDO_DE_CONTATO
    if tem_nome:
        pedido = PEDIDO_DE_TELEFONE
    elif tem_telefone:
        pedido = PEDIDO_DE_NOME
    else:
        pedido = PEDIDO_DE_NOME_E_TELEFONE
    return ABERTURA_DA_CONVERSA + pedido + FECHO_DO_PEDIDO_DE_CONTATO


# O que o corretor lê quando foi a trava, e não a pessoa, que terminou a
# conversa. Sem isto o perfil acaba na última objeção e o lead parece aberto:
# na conversa que expôs a falha, a pessoa tinha acabado de escrever que não
# ia seguir, e nada disso chegou à ficha.
#
# Vai sem consolidador de propósito: chega-se aqui porque o orçamento de
# tokens da conversa acabou, e gastar mais uma chamada de LLM para registrar
# que não há mais orçamento seria a contradição em pessoa.
NOTA_DO_HANDOVER = (
    "Atendimento entregue ao corretor automaticamente, ao atingir o limite de "
    "tokens da conversa. Não foi a pessoa que encerrou, e o motivo da saída "
    "não chegou a ser apurado. A última coisa que ela escreveu foi: "
    '"{mensagem}".'
)

# Quanto da última mensagem entra na nota. O bastante para o corretor entender
# o que estava em jogo, sem colar um parágrafo inteiro no meio do perfil.
TRECHO_DA_ULTIMA_MENSAGEM = 200


FECHAMENTO_DA_BUSCA = (
    "\n---\n"
    "Ao responder: um destaque em duas ou três linhas — o imóvel que mais combina com o que ela contou de si, com o que a descrição diz de concreto e a ligação com ELA — e até quatro alternativas de uma linha, dizendo a diferença "
    "de cada uma para o destaque. Até doze linhas.\n"
    "Abra pelo que você TEM, nunca pelo que faltou. Antes de escrever, leia as "
    "fichas acima e veja o que elas atendem do que ela pediu — muitas vezes "
    "atendem, e de outro jeito. Só diga que algo não existe depois de conferir "
    "que os imóveis realmente não têm.\n"
    "A observação da busca é anotação para você, não frase para repetir. "
    "Vire frase apenas quando a diferença mudar a decisão dela — nunca como "
    "primeira linha.\n"
    "Não ofereça um menu de próximos passos ('posso ampliar a busca, ou...') — "
    "a busca já foi refeita sozinha. Escolha você o próximo passo e termine "
    "com UMA pergunta só, ligada a um destes imóveis, que peça a reação dela e "
    "revele algo da vida dela que você ainda não sabe — 'o terceiro quarto "
    "daria um bom escritório: você trabalha de casa?'. Não sobre agendar, que "
    "vem depois de ela reagir."
)

# Menos que isto e a Marina busca de novo, uma vez, por alternativas alinhadas.
# Com um ou dois imóveis a pessoa não tem entre o que escolher, e a conversa
# morria em "gostou desse?".
MINIMO_DE_OPCOES = 3

PEDIDO_DE_COMPLEMENTO = (
    "\n---\n"
    "ANTES DE RESPONDER: vieram só {quantos} — menos de {minimo}. Chame "
    "`buscar_imoveis` mais uma vez pedindo alternativas alinhadas ao que ela "
    "quer: afrouxe o que ela não marcou como essencial — um bairro vizinho, um "
    "preço um pouco acima — e mantenha o tipo, a operação e tudo o que ela já "
    "recusou, dizendo no pedido o que ela recusou. Depois apresente tudo "
    "junto, deixando claro o que atende ao pedido e o que é alternativa."
)


def _pedido_de_complemento(ctx, quantos: int, primeira_do_turno: bool) -> str:
    """A ordem de buscar de novo, quando a lista ficou curta.

    Só na primeira busca do turno: a segunda volta com o que achou, e pedir
    uma terceira transformaria um catálogo sem opção num laço de buscas que
    custam dezenas de milhares de tokens cada.
    """
    if not primeira_do_turno or quantos >= MINIMO_DE_OPCOES:
        return ""
    rotulo = "nenhum imóvel" if quantos == 0 else f"{quantos} imóvel(is)"
    return PEDIDO_DE_COMPLEMENTO.format(quantos=rotulo, minimo=MINIMO_DE_OPCOES)


def _formatar_imovel(imovel) -> str:
    """Uma ficha por imóvel, com o que decide uma escolha.

    No aluguel o condomínio entra na conta do mês, que é o número que a pessoa
    compara. Na venda ele fica ao lado do preço, sem somar: uma parcela mensal
    e um valor à vista não se somam, mas quem compra decide com os dois.

    A descrição vai inteira. É nela que estão o lazer do condomínio, o
    acabamento e a distância da estação — o que faz alguém querer ver o imóvel,
    e o que ele responde quando a pessoa pergunta. Abreviada, o agente
    respondia "não consta no catálogo" a um dado que estava no banco.
    """
    linhas = [
        f"\n- **{imovel.titulo}** (ID: {imovel.id})",
        f"  {imovel.tipo} | {imovel.operacao} | {imovel.bairro} ({imovel.zona})",
    ]
    if imovel.operacao == "aluguel" and imovel.condominio:
        total = imovel.preco + imovel.condominio
        linhas.append(
            f"  Aluguel {reais(imovel.preco)} + condomínio "
            f"{reais(imovel.condominio)} = {reais(total)}/mês"
        )
    elif imovel.condominio:
        linhas.append(
            f"  Preço: {reais(imovel.preco)} | condomínio "
            f"{reais(imovel.condominio)}/mês"
        )
    else:
        linhas.append(f"  Preço: {reais(imovel.preco)}")
    linhas.append(
        f"  {float(imovel.area_m2):g}m² | {imovel.quartos} quartos | "
        f"{imovel.suites or 0} suítes | {imovel.banheiros or 0} banheiros | "
        f"{imovel.vaga_garagem or 0} vagas"
    )
    if imovel.perfil_indicado:
        linhas.append(f"  Indicado para: {imovel.perfil_indicado}")
    if imovel.descricao:
        linhas.append(f"  {imovel.descricao}")
    return "\n".join(linhas)


@sdr_agent.tool
@_instrumentada
async def buscar_imoveis(
    ctx: RunContext[SDRDependencies],
    pedido: Annotated[str, Field(min_length=3, max_length=400, description=(
        "O que a pessoa procura, com as palavras dela: o que quer, onde, por "
        "quanto, para quê e o que já recusou. Escreva uma frase, não uma lista "
        "de filtros — quem traduz isso em consulta é a ferramenta. Referências "
        "como 'perto da Paulista' e usos como 'para uma contabilidade de 8 "
        "pessoas' são úteis e podem entrar."))],
) -> str:
    """Buscar imóveis no catálogo de São Paulo.

    Use cedo e com pouca informação: mostrar imóvel é o que faz a pessoa
    revelar orçamento, tamanho e bairro sem você perguntar.

    A ferramenta conhece o catálogo, consulta quantas vezes precisar e amplia
    sozinha quando o pedido exato não tem resposta — a resposta diz o que
    mudou. Ela nunca troca o que foi pedido por outra coisa: quando o catálogo
    não tem, ela devolve os números reais para você dizer a verdade.

    Uma chamada basta mesmo quando a pessoa aceita comprar ou alugar: a
    ferramenta separa as duas listas sozinha.
    """
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        ficha = ficha_para_a_busca(lead)
        perfil = lead.perfil_narrativo if lead else None

    ja_vistos = imoveis_mostrados.ja_mostrados(ctx.deps.lead_id)
    # Lido antes de a busca deixar o próprio rastro: os rastros são do turno.
    primeira_do_turno = not ctx.deps.rastros_de_busca
    comeco = time.monotonic()

    try:
        recomendacao = await buscar(
            pedido=pedido,
            contexto_do_lead=ficha,
            perfil_narrativo=perfil,
            ja_mostrados=ja_vistos,
            correlation_id=ctx.deps.correlation_id,
        )
    except Exception as e:
        # A busca não pode sumir junto com uma chamada que caiu: a pessoa está
        # esperando imóvel na tela. Degrada para o caminho sem LLM, que monta
        # filtros da ficha dela e usa a escada de relaxamento do catálogo.
        logger.warning(
            "event=busca_com_agente_falhou lead_id=%s tipo_erro=%s "
            "acao=busca_estruturada",
            ctx.deps.lead_id, type(e).__name__,
        )
        _registrar_custo_da_busca(
            ctx, comeco, erro=type(e).__name__, tokens=(0, 0)
        )
        return _busca_sem_agente(ctx, pedido)

    _registrar_custo_da_busca(
        ctx, comeco, tokens=(recomendacao.tokens_in, recomendacao.tokens_out)
    )

    if not recomendacao.ids:
        # Lista vazia de uma busca que rodou é a resposta, e não uma falha.
        # Mandá-la para a degradação trocava o julgamento do agente — que leu
        # o pedido, o perfil e o que já foi mostrado — por filtros afrouxados
        # da ficha: numa conversa real, quem recusou apartamento e 3 quartos
        # recebeu de volta, três vezes, os mesmos apartamentos de 3 quartos e
        # o sobrado que já tinha dispensado.
        return _sem_imovel_que_sirva(ctx, recomendacao, ja_vistos, primeira_do_turno)

    with get_db() as db:
        # Os números saem do banco, sempre: o agente de busca devolve IDs e
        # julgamento, e preço escrito por modelo é exatamente o que a persona
        # promete à pessoa que nunca vai acontecer.
        imoveis = ctx.deps.catalog_service.get_by_ids(recomendacao.ids, db)

        if len(imoveis) < len(recomendacao.ids):
            logger.warning(
                "event=imovel_recomendado_sem_correspondencia lead_id=%s "
                "pedidos=%s encontrados=%s",
                ctx.deps.lead_id, recomendacao.ids, [i.id for i in imoveis],
            )

        if not imoveis:
            # O agente devolveu IDs que não existem no banco. Aí sim a
            # degradação é melhor que a mão vazia, e o que ela achar vem com
            # a observação junto.
            return _busca_sem_agente(ctx, pedido, recomendacao.observacao)

        apresentados = [i.id for i in imoveis]
        imoveis_mostrados.registrar(ctx.deps.lead_id, apresentados)
        _guardar_rastro(ctx, apresentados, recomendacao)
        # A formatação fica dentro da sessão: os objetos são do ORM e acessar
        # um atributo depois do close levanta DetachedInstanceError.
        return _texto_da_recomendacao(imoveis, recomendacao) + _pedido_de_complemento(
            ctx, len(imoveis), primeira_do_turno
        )


# Quantas fichas `detalhar_imoveis` devolve quando não recebe IDs. Dez cobre
# as últimas buscas da conversa com folga; a lista inteira de uma conversa
# longa seriam alguns milhares de tokens para responder "quantas vagas tem".
TETO_DO_DETALHAMENTO = 10


@sdr_agent.tool
@_instrumentada
async def detalhar_imoveis(
    ctx: RunContext[SDRDependencies],
    imovel_ids: Annotated[Optional[list[int]], Field(description=(
        "IDs específicos, quando você os tem. Deixe vazio para receber os "
        "últimos que você apresentou a esta pessoa — é o caso comum, porque o "
        "histórico da conversa não guarda todos."))] = None,
) -> str:
    """Reler a ficha completa de imóveis que você já apresentou.

    Use para qualquer pergunta sobre um imóvel que já está na conversa: preço,
    metragem, quartos, suítes, vagas, condomínio, bairro. A resposta vem do
    catálogo na hora, sem custo e sem demora.

    É esta a ferramenta, e não `buscar_imoveis`, quando o que ela quer é saber
    mais sobre o que você mostrou. Buscar de novo custa dezenas de milhares de
    tokens e traz imóveis diferentes, que não é o que ela perguntou.

    Também é por aqui que você recupera o ID de cada imóvel para escrever
    na `observacoes` de `agendar_reuniao`.
    """
    with get_db() as db:
        pedidos = imovel_ids or ctx.deps.lead_service.imoveis_apresentados(
            ctx.deps.lead_id, db
        )[-TETO_DO_DETALHAMENTO:]

        if not pedidos:
            return (
                "Você ainda não apresentou imóvel nenhum a esta pessoa. Use "
                "`buscar_imoveis` descrevendo o que ela procura."
            )

        imoveis = ctx.deps.catalog_service.get_by_ids(pedidos, db)
        if not imoveis:
            return (
                f"Nenhum dos IDs {pedidos} existe no catálogo ou está "
                f"disponível. Chame de novo sem informar IDs para receber o "
                f"que você de fato apresentou."
            )

        faltaram = [i for i in pedidos if i not in {im.id for im in imoveis}]
        linhas = [f"{len(imoveis)} imóvel(is) que você já apresentou:"]
        linhas.extend(_formatar_imovel(imovel) for imovel in imoveis)
        if faltaram:
            linhas.append(
                f"\nSem correspondência no catálogo: {faltaram}. Não fale "
                f"deles com a pessoa."
            )
        return "\n".join(linhas)


def _texto_da_recomendacao(imoveis, recomendacao) -> str:
    """A ficha de cada imóvel, com o porquê que o agente de busca escreveu.

    Os imóveis vêm primeiro e a observação da busca vem depois deles, de
    propósito. A ordem em que o modelo lê é a ordem em que ele tende a
    escrever: com a observação no topo, uma anotação como "não achei a
    combinação exata" virava a primeira linha da mensagem, antes de três
    imóveis que atendiam ao pedido por outro caminho.
    """
    porque_de = {e.imovel_id: e.porque for e in recomendacao.escolhidos}

    linhas = [f"Encontrei {len(imoveis)} imóvel(is):"]
    for imovel in imoveis:
        linhas.append(_formatar_imovel(imovel))
        if porque := porque_de.get(imovel.id):
            linhas.append(f"  → {porque}")

    if recomendacao.observacao:
        linhas.append(_nota_da_busca(recomendacao.observacao))

    linhas.append(FECHAMENTO_DA_BUSCA)
    return "\n".join(linhas)


FECHAMENTO_SEM_IMOVEL = (
    "\n---\n"
    "Ao responder: nada no catálogo atende ao que ela pediu. Diga isso em uma "
    "linha, sem pedir desculpa e sem repetir o pedido inteiro.\n"
    "Se acima houver um imóvel mais próximo, apresente-o em uma ou duas "
    "linhas — o que é, o preço e no que difere do pedido —, sem vendê-lo como "
    "se atendesse. Sem ele, use a nota da busca para dizer o que o catálogo "
    "tem.\n"
    "Não volte a oferecer imóvel que ela já recusou nesta conversa.\n"
    "Termine com UMA pergunta: se ela quer conhecer o mais próximo, ou o que "
    "aceita mudar — bairro, tipo, quartos ou preço."
)


def _sem_imovel_que_sirva(
    ctx, recomendacao, ja_vistos: list[int], primeira_do_turno: bool = False
) -> str:
    """O retorno quando a busca rodou e concluiu que nada atende.

    Sem lista de imóveis e sem o fechamento de apresentação: com os dois, a
    Marina apresentava o que tinha na mão, atendesse ou não. A alternativa
    mais próxima vem com a ficha relida do banco, rotulada como o que ela é —
    o preço que a Marina citar sai do PostgreSQL, não da nota do agente.
    """
    linhas = ["Nenhum imóvel do catálogo atende ao pedido."]
    apresentados: list[int] = []

    alternativa = recomendacao.mais_proximo
    if alternativa is not None and alternativa not in ja_vistos:
        with get_db() as db:
            achados = ctx.deps.catalog_service.get_by_ids([alternativa], db)
            if achados:
                linhas.append("\nO mais próximo, que NÃO atende ao pedido:")
                linhas.append(_formatar_imovel(achados[0]))
                apresentados = [alternativa]

    if apresentados:
        imoveis_mostrados.registrar(ctx.deps.lead_id, apresentados)
    _guardar_rastro(ctx, apresentados, recomendacao)

    if recomendacao.observacao:
        linhas.append(_nota_da_busca(recomendacao.observacao))
    linhas.append(FECHAMENTO_SEM_IMOVEL)
    return "\n".join(linhas) + _pedido_de_complemento(
        ctx, len(apresentados), primeira_do_turno
    )


def _nota_da_busca(texto: str) -> str:
    """Rotula o que a busca anotou como contexto, e não como frase pronta.

    Sem o rótulo o modelo copia a anotação para a mensagem, e ela está escrita
    do ponto de vista de quem procurou — descreve a busca, não os imóveis.
    """
    return (
        "\n---\n"
        f"Nota da busca, para o seu entendimento e não para copiar: {texto}"
    )


def _registrar_custo_da_busca(
    ctx: RunContext[SDRDependencies],
    comeco: float,
    tokens: tuple[int, int],
    erro: Optional[str] = None,
) -> None:
    """Grava o consumo do agente de busca com `operation="busca"`.

    Separado de `chat` de propósito: são tokens do mesmo lead, e entram no
    orçamento dele, mas não contam como turno de conversa para o limite que
    dispara o handover. Os agentes auxiliares trabalham dentro de um turno, não
    no lugar dele.
    """
    with get_db() as db:
        if erro:
            ctx.deps.llm_usage_service.record_failure(
                lead_id=ctx.deps.lead_id,
                model=modelo_da_busca(),
                operation="busca",
                error_type=erro,
                latency_ms=_decorrido_ms(comeco),
                db=db,
            )
            return
        entrada, saida = tokens
        ctx.deps.llm_usage_service.record(
            lead_id=ctx.deps.lead_id,
            model=modelo_da_busca(),
            tokens_in=entrada,
            tokens_out=saida,
            operation="busca",
            latency_ms=_decorrido_ms(comeco),
            db=db,
        )


def _guardar_rastro(
    ctx: RunContext[SDRDependencies],
    imovel_ids: list[int],
    recomendacao=None,
) -> None:
    """Anota no `metadata_json` da mensagem o que esta busca apresentou.

    Duas coisas, com donos diferentes.

    `imovel_ids` é o registro durável do que a pessoa viu. O retorno da busca é
    abreviado em 900 caracteres ao voltar ao histórico, e medido numa conversa
    real isso derrubou metade dos IDs — três de seis. Sem este registro, uma
    pergunta sobre o terceiro imóvel da lista, ou um pedido de visita a ele,
    só se resolveria buscando tudo de novo. É daqui que `detalhar_imoveis` lê.

    `consultas` é o rastro de como o agente de busca chegou lá. Elas não viram
    mensagem — é o que torna a delegação barata —, então este é o único lugar
    onde ficam. Ausentes no caminho de degradação, que não usa LLM.

    Tudo amarrado pelo `tool_call_id`: um turno pode ter mais de uma busca, e
    `_registrar_ferramentas_do_turno` precisa saber qual rastro é de qual
    chamada.
    """
    rastro: dict = {"imovel_ids": imovel_ids}
    if recomendacao is not None:
        rastro["consultas"] = recomendacao.consultas
        rastro["tokens_in"] = recomendacao.tokens_in
        rastro["tokens_out"] = recomendacao.tokens_out
    ctx.deps.rastros_de_busca[ctx.tool_call_id] = rastro


def _busca_sem_agente(
    ctx: RunContext[SDRDependencies],
    pedido: str,
    observacao: str = "",
) -> str:
    """Busca estruturada a partir da ficha do lead, sem LLM nenhum.

    O caminho de degradação. Os filtros vêm do que já está gravado sobre a
    pessoa, o pedido inteiro vira termo livre e a escada de relaxamento do
    `CatalogService` faz o resto. A busca degrada em qualidade, não em
    disponibilidade: a pessoa recebe imóveis piores, não um pedido de
    desculpas.
    """
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        filtros = _filtros_da_ficha(lead, pedido)

        try:
            resultado = ctx.deps.catalog_service.search_relaxando(db, **filtros)
        except FiltroInvalido as e:
            # Contradição na própria ficha do lead (uma faixa de orçamento
            # invertida, por exemplo). Sem preço é melhor que sem imóvel.
            logger.warning(
                "event=ficha_com_filtro_invalido lead_id=%s motivo=%s",
                ctx.deps.lead_id, e,
            )
            filtros.pop("preco_min", None)
            filtros.pop("preco_max", None)
            resultado = ctx.deps.catalog_service.search_relaxando(db, **filtros)

        if not resultado.imoveis:
            return "\n".join(filter(None, [observacao, _nada_encontrado(resultado)]))

        apresentados = [i.id for i in resultado.imoveis]
        imoveis_mostrados.registrar(ctx.deps.lead_id, apresentados)
        _guardar_rastro(ctx, apresentados)

        linhas = [f"Encontrei {len(resultado.imoveis)} imóvel(is):"]
        linhas.extend(_formatar_imovel(imovel) for imovel in resultado.imoveis)

        # Depois das fichas, e rotulado: o agente precisa das palavras exatas
        # do que mudou — sem elas ele inventa que ampliou a busca sem ter
        # ampliado —, mas lendo isso antes dos imóveis ele abre a mensagem
        # pelo que faltou.
        notas = [observacao] if observacao else []
        if resultado.relaxamentos:
            notas.append(
                "com os filtros exatos não havia nada, então a busca foi "
                "refeita " + " e ".join(resultado.relaxamentos) + "."
            )
        if notas:
            linhas.append(_nota_da_busca(" ".join(notas)))

        linhas.append(FECHAMENTO_DA_BUSCA)
        return "\n".join(linhas)


def _filtros_da_ficha(lead, pedido: str) -> dict:
    """Filtros do catálogo montados do que já está gravado sobre a pessoa.

    É o que sobra quando não há LLM para interpretar o pedido: o texto inteiro
    vira termo livre, e quem restringe são os campos que ela já informou.
    """
    return dict(
        operacao=OPERACAO_POR_INTENCAO.get(getattr(lead, "intencao", None) or ""),
        bairro=getattr(lead, "bairro_interesse", None),
        zona=getattr(lead, "regiao_interesse", None),
        preco_min=getattr(lead, "orcamento_min", None),
        preco_max=getattr(lead, "orcamento_max", None),
        quartos_min=getattr(lead, "quartos", None),
        termos_livres=pedido,
        limite=5,
    )


def _nada_encontrado(resultado) -> str:
    """Lista vazia é resposta válida, e precisa ser útil.

    Zero resultado não é erro: é informação sobre o catálogo. O que torna isso
    acionável são os números — quantos existem, qual o mais barato, em que
    bairros há — porque é com eles que o agente diz o que existe de verdade em
    vez de pedir desculpa no vazio.
    """
    linhas = ["Nenhum imóvel encontrado."]
    if resultado.relaxamentos:
        linhas.append(
            "Já tentei, sem sucesso: " + "; ".join(resultado.relaxamentos) + "."
        )
    linhas.extend(resultado.diagnostico)
    linhas.append(
        "Diga à pessoa o que o catálogo realmente tem, com estes números. Não "
        "ofereça um imóvel de outro tipo como se fosse o que ela pediu, e não "
        "devolva a busca para ela refinar."
    )
    return "\n".join(linhas)


# Telefone brasileiro: 10 digitos com fixo, 11 com celular, os dois com DDD.
# O 55 na frente aparece quando a pessoa copia do proprio WhatsApp.
_DDI_BR = "55"


def _telefone_normalizado(bruto: str) -> str:
    """Telefone em `(11) 98765-4321`, ou `ModelRetry` se não der para ler.

    A pessoa escreve de todo jeito — com ponto, com +55, sem DDD. Guardar o
    texto cru deixaria a ficha do corretor com meia dúzia de formatos e
    números incompletos que só se descobre inválidos na hora de ligar.

    Recusar com `ModelRetry` é melhor que gravar errado: o modelo volta e
    pergunta o DDD, que é justamente o que falta na maioria dos casos.
    """
    digitos = "".join(c for c in bruto if c.isdigit())
    if len(digitos) in (12, 13) and digitos.startswith(_DDI_BR):
        digitos = digitos[2:]

    if len(digitos) not in (10, 11):
        raise ModelRetry(
            f"'{bruto}' não é um telefone que dê para usar. Preciso de DDD "
            f"mais o número, como (11) 98765-4321. Pergunte o DDD se ela não "
            f"tiver dito."
        )

    ddd, resto = digitos[:2], digitos[2:]
    return f"({ddd}) {resto[:-4]}-{resto[-4:]}"


@sdr_agent.tool
@_instrumentada
async def registrar_qualificacao(
    ctx: RunContext[SDRDependencies],
    nome: Annotated[Optional[str], Field(max_length=120, description=(
        "Como a pessoa se chama, do jeito que ela disse. Só o nome — nada de "
        "'Sr.' nem sobrenome inventado. Grave assim que souber."))] = None,
    telefone: Annotated[Optional[str], Field(max_length=30, description=(
        "Telefone com DDD, como ela escreveu. É por aqui que o corretor liga: "
        "sem isso uma visita marcada não serve para nada."))] = None,
    intencao: Annotated[Optional[str], Field(
        description="Exatamente um de: compra, aluguel, investimento.")] = None,
    perfil: Annotated[Optional[str], Field(max_length=30, description=(
        "Categoria curta do lead, até 30 caracteres e sem frases. "
        "Ex.: residencial, investidor, primeiro_imovel, corporativo."))] = None,
    orcamento_min: Optional[float] = None,
    orcamento_max: Optional[float] = None,
    bairro_interesse: Annotated[Optional[str], Field(max_length=80, description=(
        "Somente o nome do bairro. Ex.: Bela Vista."))] = None,
    regiao_interesse: Annotated[Optional[str], Field(max_length=80, description=(
        "Região ou zona da cidade. Ex.: zona leste."))] = None,
    quartos: Optional[int] = None,
    urgencia: Annotated[Optional[str], Field(
        description="Exatamente um de: baixa, media, alta.")] = None,
    motivo_busca: Annotated[Optional[str], Field(max_length=120, description=(
        "Motivo da busca em poucas palavras. Ex.: mudança de trabalho."))] = None,
    forma_pagamento: Annotated[Optional[str], Field(max_length=30, description=(
        "Termo curto. Ex.: a_vista, financiamento, fgts."))] = None,
    amenidades_desejadas: Annotated[Optional[str], Field(description=(
        "Lista curta separada por vírgula. Ex.: piscina, academia."))] = None,
    tipologia_interesse: Annotated[Optional[str], Field(max_length=30, description=(
        "Tipo de imóvel em uma palavra. Ex.: apartamento, casa, studio."))] = None,
) -> str:
    """Registrar ou atualizar dados de qualificação estruturados do lead.

    Use campos curtos e padronizados. Texto livre e narrativa do lead vão em
    `atualizar_perfil_lead`, não aqui.
    """
    data = {k: v for k, v in locals().items() if k != 'ctx' and v is not None}
    if telefone is not None:
        data["telefone"] = _telefone_normalizado(telefone)
    with get_db() as db:
        lead = ctx.deps.lead_service.update_qualification(ctx.deps.lead_id, data, db)
        # Recalculate score
        score = ctx.deps.lead_service.calculate_score(ctx.deps.lead_id, db)
        return f"Lead atualizado com sucesso. Score atual: {score}"


@sdr_agent.tool
@_instrumentada
async def atualizar_perfil_lead(
    ctx: RunContext[SDRDependencies],
    novidades: Annotated[str, Field(min_length=3, description=(
        "O que esta conversa acabou de revelar sobre a pessoa, em uma ou duas "
        "frases: uma preferência, uma restrição, uma objeção, o motivo de ter "
        "recusado um imóvel, o contexto de vida dela. Recusa vai com o motivo "
        "que ela deu, sem estender às outras características do imóvel. "
        "Escreva SÓ a novidade — o perfil que já existe é preservado e não "
        "precisa ser repetido."))],
) -> str:
    """Registrar no perfil narrativo algo qualitativo que a conversa revelou.

    O que você escreve aqui é fundido ao perfil que já existe; nada do que
    estava lá se perde. Use para o que não cabe em campo padronizado: por que
    ela recusou um imóvel, o que valoriza, como é a vida dela. Orçamento,
    bairro, quartos e telefone vão em `registrar_qualificacao`.
    """
    if not await _anotar_no_perfil(ctx, novidades):
        return "Lead não encontrado."
    return "Perfil narrativo atualizado."


async def _anotar_no_perfil(ctx: RunContext[SDRDependencies], novidades: str) -> bool:
    """Funde `novidades` ao perfil do lead pelo consolidador. Falso se não há lead.

    Fica separado da tool porque o encerramento do atendimento anota pelo
    mesmo caminho: o motivo da saída é informação de perfil como qualquer
    outra, e escrevê-la por outra via daria dois jeitos de montar o mesmo
    texto — que foi o que fez o perfil encolher antes de haver consolidador.
    """
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        if lead is None:
            return False
        perfil_atual = lead.perfil_narrativo

    comeco = time.monotonic()
    try:
        consolidado = await consolidar_perfil(perfil_atual, novidades)
        texto = consolidado.texto
        registrar = functools.partial(
            ctx.deps.llm_usage_service.record,
            tokens_in=consolidado.tokens_in,
            tokens_out=consolidado.tokens_out,
        )
    except Exception as e:
        # A novidade não pode se perder junto com a chamada: ela é a única
        # cópia do que a pessoa acabou de contar. Vai emendada ao fim do
        # perfil, sem consolidação, e o corretor lê tudo do mesmo jeito.
        logger.warning(
            "event=consolidacao_de_perfil_falhou lead_id=%s tipo_erro=%s "
            "acao=anexado_sem_consolidar",
            ctx.deps.lead_id, type(e).__name__,
        )
        texto = juntar_sem_llm(perfil_atual, novidades)
        registrar = functools.partial(
            ctx.deps.llm_usage_service.record_failure,
            error_type=type(e).__name__,
        )

    with get_db() as db:
        # `operation="perfil"` separa este custo do turno de conversa: são
        # tokens do mesmo lead, e entram no orçamento dele, mas não contam
        # como turno para o limite que dispara o handover.
        registrar(
            lead_id=ctx.deps.lead_id,
            model=settings.LLM_MODEL,
            operation="perfil",
            latency_ms=_decorrido_ms(comeco),
            db=db,
        )
        ctx.deps.lead_service.update_perfil_narrativo(ctx.deps.lead_id, texto, db)
    return True


@sdr_agent.tool
@_instrumentada
async def agendar_reuniao(
    ctx: RunContext[SDRDependencies],
    tipo: Annotated[str, Field(description="Exatamente um de: visita, reuniao.")],
    data_hora: Annotated[str, Field(description="Data e hora no formato YYYY-MM-DD HH:MM.")],
    observacoes: Annotated[Optional[str], Field(description=(
        "O que o corretor precisa saber antes de ir. Numa visita, comece "
        "pelos imóveis que a pessoa quer ver, com o ID de cada um — ex.: "
        "'Quer ver os imóveis 142 (sobrado na Mooca) e 144 (Tatuapé)'. "
        "Depois, o que pesa na decisão dela."))] = None,
    remarcar: Annotated[bool, Field(description=(
        "Só `true` quando a pessoa JÁ disse que quer trocar o compromisso que "
        "ela tem marcado por este novo horário. Nunca use para contornar o "
        "aviso de compromisso existente sem ter perguntado a ela."))] = False,
) -> str:
    """Registrar visita ou reunião para handover ao corretor.

    Um compromisso de pé por pessoa. Havendo outro, a ferramenta avisa e não
    marca: combine a troca com ela e chame de novo com `remarcar=true`.
    """
    if tipo not in ("visita", "reuniao"):
        return "Tipo inválido. Use 'visita' ou 'reuniao'."

    try:
        dt = para_guardar(datetime.strptime(data_hora, "%Y-%m-%d %H:%M"))
    except ValueError:
        return "Formato de data inválido. Use YYYY-MM-DD HH:MM."

    with get_db() as db:
        if tipo == "visita":
            _exigir_observacao(ctx, observacoes)
        try:
            agendamento = ctx.deps.scheduling_service.create(
                lead_id=ctx.deps.lead_id,
                tipo=tipo,
                data_hora=dt,
                observacoes=observacoes,
                db=db,
                remarcar=remarcar,
            )
        except CompromissoJaMarcado as conflito:
            return _aviso_de_compromisso_existente(ctx, conflito.existente)

        return (
            f"Agendamento criado com sucesso!\n"
            f"Tipo: {agendamento.tipo}\n"
            f"Data/Hora: {data_hora}\n"
            f"Status: {agendamento.status}"
            + _falta_para_o_corretor(ctx, db)
        )


def _exigir_observacao(ctx: RunContext[SDRDependencies], observacoes) -> None:
    """Recusa a visita que chega sem observação.

    O compromisso não aponta para uma linha do catálogo: quem diz o que será
    visitado é este texto, e é ele que o corretor lê junto do perfil e do
    resumo. Vazio, o handover vira um horário e nada mais — aconteceu de
    verdade, com o agente marcando "sábado às 10h na Bela Vista" e o corretor
    sem saber aonde ir.

    Só cobra que exista. Conferir o conteúdo — se cita imóvel, se o ID é de um
    já apresentado — é adivinhar a intenção de um texto livre, e a ferramenta
    erraria nos dois sentidos.
    """
    if (observacoes or "").strip():
        return

    logger.info(
        "event=visita_sem_observacao lead_id=%s acao=recusada", ctx.deps.lead_id
    )
    raise ModelRetry(
        "Esta visita não diz o que será visitado. O agendamento não guarda o "
        "imóvel em campo próprio — quem diz isso ao corretor é a "
        "`observacoes`, e é ela que ele lê junto do perfil e do resumo. "
        "Chame de novo com os imóveis que a pessoa quer ver e o ID de cada "
        "um, e com o que pesa na decisão dela. Se não lembrar de qual imóvel "
        "é qual, `detalhar_imoveis` devolve as fichas na hora."
    )


def _aviso_de_compromisso_existente(
    ctx: RunContext[SDRDependencies], existente
) -> str:
    """O texto que o modelo lê quando tenta marcar sobre um compromisso de pé.

    Volta como retorno, e não como `ModelRetry`: a correção não está com o
    modelo, está com a pessoa. Ele precisa perguntar se ela quer trocar, e só
    então insistir — uma retentativa imediata marcaria por cima de um
    compromisso que ela talvez queira manter.
    """
    logger.info(
        "event=agendamento_sobre_compromisso_ativo lead_id=%s agendamento_id=%s "
        "acao=avisado",
        ctx.deps.lead_id, existente.id,
    )
    return (
        f"Esta pessoa já tem {existente.tipo} marcada para "
        f"{formatar(existente.data_hora)} ({existente.status}), e só se marca "
        f"um compromisso por vez. Nada foi alterado.\n"
        f"Pergunte a ela se quer trocar por este novo horário. Se ela disser "
        f"que sim, chame esta ferramenta de novo com `remarcar=true`. Se ela "
        f"só quis confirmar o que já existe, use `confirmar_agendamento`."
    )


def _falta_para_o_corretor(ctx: RunContext[SDRDependencies], db) -> str:
    """Cobra nome e telefone que ainda faltem quando a visita é marcada.

    Os dois se pedem cedo, mas sem insistir, e a pessoa pode não ter dado.
    Marcar visita é o momento em que o dado deixa de ser opcional: é um
    corretor de carne e osso que vai ligar, e essa é uma razão que ela entende.

    Vai no retorno da tool, e não só nas instruções, porque este texto é a
    última coisa que o modelo lê antes de escrever — é onde a ordem pega.
    """
    lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
    falta = [
        rotulo
        for rotulo, valor in (("o nome", lead.nome), ("o telefone", lead.telefone))
        if not valor
    ]
    if not falta:
        return ""
    return (
        f"\n---\nVocê ainda não tem {' nem '.join(falta)} desta pessoa, e um "
        "corretor vai ligar para confirmar esta visita. Peça na mesma mensagem "
        "em que confirma o agendamento, e grave com `registrar_qualificacao`."
    )


# O que confirmar e cancelar respondem quando não há o que confirmar ou
# cancelar. Dizer só "não existe" fazia o modelo desistir e contar isso à
# pessoa; com a saída na própria recusa, ele segue sozinho.
SEM_COMPROMISSO = (
    "Esta pessoa não tem compromisso de pé. Se ela quer marcar um, use "
    "`agendar_reuniao`; se ela está falando de algo que já aconteceu ou que "
    "já foi cancelado, diga isso a ela em vez de mexer na agenda."
)


@sdr_agent.tool
@_instrumentada
async def listar_agendamentos(ctx: RunContext[SDRDependencies]) -> str:
    """Consultar o compromisso marcado desta pessoa.

    Use quando ela perguntar o que tem marcado ou quando for a visita. A
    resposta vem do banco no momento da chamada.

    A mesma informação abre as suas instruções, mas ali ela fica antes de toda
    a conversa; chamando aqui você a recebe agora, depois dela.
    """
    return texto_dos_compromissos(ctx.deps.lead_id)


@sdr_agent.tool
@_instrumentada
async def confirmar_agendamento(ctx: RunContext[SDRDependencies]) -> str:
    """Marcar como confirmado o compromisso que a pessoa disse que vai cumprir.

    Só quando ela confirmar de forma clara. Diante de hesitação ou de resposta
    vaga, não chame esta ferramenta: pergunte.

    Não recebe qual compromisso: é um só por pessoa, e o serviço o encontra
    pelo lead. Enquanto o ID era argumento, errá-lo alcançava o compromisso de
    outra pessoa — e o modelo o errava, pegando números antigos na conversa.
    """
    with get_db() as db:
        agendamento = ctx.deps.scheduling_service.compromisso_ativo(
            ctx.deps.lead_id, db
        )
        if agendamento is None:
            return SEM_COMPROMISSO
        if agendamento.status == "confirmado":
            return (
                f"A {agendamento.tipo} de "
                f"{formatar(agendamento.data_hora)} já estava confirmada."
            )

        atual = ctx.deps.scheduling_service.update_status(
            agendamento.id, "confirmado", db
        )
        return f"Confirmado: {atual.tipo} em {formatar(atual.data_hora)}."


@sdr_agent.tool
@_instrumentada
async def cancelar_agendamento(
    ctx: RunContext[SDRDependencies],
    motivo: Annotated[str, Field(max_length=120, description=(
        "O que a pessoa disse, em poucas palavras. Ex.: viajou na data."))],
) -> str:
    """Cancelar o compromisso que a pessoa disse que não vai cumprir.

    Só com uma decisão explícita dela. "Acho que não consigo" ou "vou ver" não
    é cancelamento — é dúvida, e o caminho é perguntar ou oferecer remarcar.
    Cancelar tira um compromisso da agenda do corretor.

    Para remarcar não use esta ferramenta: `agendar_reuniao` com
    `remarcar=true` faz as duas coisas e deixa o motivo registrado.
    """
    with get_db() as db:
        agendamento = ctx.deps.scheduling_service.compromisso_ativo(
            ctx.deps.lead_id, db
        )
        if agendamento is None:
            return SEM_COMPROMISSO

        tipo, quando = agendamento.tipo, agendamento.data_hora
        ctx.deps.scheduling_service.update_status(agendamento.id, "cancelado", db)
        ctx.deps.lead_service.save_message(
            lead_id=ctx.deps.lead_id,
            channel=ctx.deps.channel,
            role="system",
            content=f"Cancelamento pedido pelo lead: {motivo}",
            message_type="system_notice",
            db=db,
        )
        return (
            f"Cancelado: {tipo} em {formatar(quando)}. O corretor verá o "
            f"motivo registrado."
        )


# O que pode ter acontecido para não haver mais o que fazer pela conversa.
Desfecho = Literal["agendou", "desistiu", "pediu_corretor"]

# Desfechos em que o lead sai do alcance das réguas de follow-up. `agendado`
# fica de fora de propósito: o compromisso de pé ainda precisa do lembrete de
# confirmação, que é a régua `pos_agendamento`.
DESFECHOS_QUE_ENCERRAM = ("desistiu", "pediu_corretor")


@sdr_agent.tool
@_instrumentada
async def encerrar_atendimento(
    ctx: RunContext[SDRDependencies],
    desfecho: Annotated[Desfecho, Field(description=(
        "'agendou' quando a visita ou reunião já está marcada e não falta "
        "nada; 'desistiu' quando a pessoa disse que não quer seguir; "
        "'pediu_corretor' quando ela quer falar com uma pessoa."))],
    motivo: Annotated[str, Field(max_length=200, description=(
        "O que ela disse, na linguagem dela e em uma frase. Ex.: 'achou tudo "
        "acima do orçamento depois de ver três opções'. Esta frase é o que o "
        "corretor lê para saber por que a conversa terminou assim."))],
) -> str:
    """Fechar o atendimento quando não há mais nada que você possa fazer.

    Faz três coisas de uma vez: registra o motivo no perfil, gera o resumo
    executivo para o corretor e tira a pessoa da régua de follow-up quando o
    caso é de saída. Depois disto, agradeça e encerre — sem nova pergunta.

    Só chame quando o assunto realmente acabou. Dúvida, silêncio ou "vou
    pensar" não é desistência: é conversa em aberto, e quem retoma é o
    follow-up, não você.
    """
    with get_db() as db:
        marcado = ctx.deps.scheduling_service.tem_compromisso_ativo(
            ctx.deps.lead_id, db
        )

    # Os dois desencontros possíveis entre o que o modelo diz e o que o banco
    # mostra. Ambos deixariam a agenda do corretor errada, e nenhum dos dois
    # ele consegue perceber sozinho depois.
    if desfecho == "agendou" and not marcado:
        logger.info(
            "event=encerramento_sem_compromisso lead_id=%s acao=recusado",
            ctx.deps.lead_id,
        )
        raise ModelRetry(
            "Não há nenhum compromisso de pé para esta pessoa, então o "
            "atendimento não terminou em agendamento. Marque com "
            "`agendar_reuniao` antes de encerrar, ou encerre com o desfecho "
            "que realmente aconteceu."
        )
    if desfecho in DESFECHOS_QUE_ENCERRAM and marcado:
        logger.info(
            "event=encerramento_com_compromisso_de_pe lead_id=%s acao=recusado",
            ctx.deps.lead_id,
        )
        raise ModelRetry(
            "Esta pessoa tem compromisso de pé na agenda do corretor. "
            "Encerrar agora apagaria o lembrete de confirmação e ele "
            "iria ao imóvel à toa. Use `cancelar_agendamento` primeiro, "
            "e só então encerre."
        )

    if not await _anotar_no_perfil(ctx, f"Encerrou o atendimento: {motivo}."):
        return "Lead não encontrado."

    with get_db() as db:
        if desfecho in DESFECHOS_QUE_ENCERRAM:
            # `inativo` é o único status fora dos `status_alvo` de todas as
            # réguas: é assim que a pessoa para de receber follow-up. Se ela
            # voltar a escrever, `process_message` a devolve à qualificação.
            ctx.deps.lead_service.update_status(ctx.deps.lead_id, "inativo", db)

        resumo = SummaryService().generate_resumo(ctx.deps.lead_id, db)
        ctx.deps.lead_service.update_qualification(
            ctx.deps.lead_id, {"resumo": resumo}, db
        )

    logger.info(
        "event=atendimento_encerrado lead_id=%s desfecho=%s",
        ctx.deps.lead_id, desfecho,
    )
    # O resumo em si não volta: ele é para o corretor ler na ficha, e mandá-lo
    # de volta ao modelo custaria alguns milhares de tokens para nada.
    return (
        "Atendimento encerrado e resumo entregue ao corretor. Agora agradeça "
        "em uma ou duas linhas, diga o que acontece a seguir e termine sem "
        "fazer pergunta nenhuma."
    )


def _formatar_orcamento(lead) -> Optional[str]:
    if lead.orcamento_min and lead.orcamento_max:
        return f"Orçamento: de {reais(lead.orcamento_min)} a {reais(lead.orcamento_max)}"
    if lead.orcamento_max:
        return f"Orçamento: até {reais(lead.orcamento_max)}"
    if lead.orcamento_min:
        return f"Orçamento: a partir de {reais(lead.orcamento_min)}"
    return None


# O que conta como lacuna de qualificação, e o nome pelo qual falamos disso.
LACUNAS = (
    ("intencao", "se é compra, aluguel ou investimento"),
    ("orcamento", "orçamento"),
    ("localizacao", "região ou bairro"),
    ("quartos", "quantos quartos"),
    # Nunca "urgência": a anotação vira pergunta, e ninguém responde "qual é a
    # sua urgência?". O rótulo é a pergunta que uma pessoa faria.
    ("urgencia", "para quando ela precisa mudar"),
)


def _o_que_se_sabe(lead) -> list[str]:
    """Os dados estruturados já gravados do lead, em linguagem de gente.

    Lista só o que existe. Enumerar todos os campos, com "Não informado" ao
    lado dos vazios, entrega ao modelo um formulário em branco — e é assim que
    ele passa a conduzir a conversa, pedindo campo por campo.
    """
    sabido = []
    if lead.nome:
        sabido.append(f"Nome: {lead.nome}")
    if lead.intencao:
        sabido.append(f"Quer: {lead.intencao}")
    if lead.tipologia_interesse:
        sabido.append(f"Tipo de imóvel: {lead.tipologia_interesse}")
    if orcamento := _formatar_orcamento(lead):
        sabido.append(orcamento)
    if lead.bairro_interesse:
        sabido.append(f"Bairro: {lead.bairro_interesse}")
    if lead.regiao_interesse:
        sabido.append(f"Região: {lead.regiao_interesse}")
    if lead.quartos is not None:
        sabido.append(f"Quartos: {lead.quartos}")
    if lead.urgencia:
        sabido.append(f"Urgência: {lead.urgencia}")
    if lead.forma_pagamento:
        sabido.append(f"Forma de pagamento: {lead.forma_pagamento}")
    if lead.motivo_busca:
        sabido.append(f"Motivo da busca: {lead.motivo_busca}")
    if lead.amenidades_desejadas:
        sabido.append(f"Quer que tenha: {lead.amenidades_desejadas}")
    return sabido


def ficha_para_a_busca(lead) -> str:
    """O que se sabe da pessoa, para o agente de busca desempatar.

    Só os dados dela. O estágio no funil, as lacunas de qualificação e a agenda
    de compromissos ficam de fora: são assunto de quem conversa, e no contexto
    de quem procura imóvel seriam tokens gastos em nada.
    """
    if lead is None:
        return ""
    return "\n".join(f"- {item}" for item in _o_que_se_sabe(lead))


def montar_contexto_do_lead(lead) -> str:
    """Resume o que já se sabe do lead para dentro das instruções do turno."""
    if lead is None:
        return "Primeira mensagem desta pessoa. Você ainda não sabe nada sobre ela."

    sabido = _o_que_se_sabe(lead)
    # O telefone se pede cedo; sem esta linha o modelo não sabe que já o tem e
    # pede de novo. Só o fato, não o número: a conversa não precisa dele.
    if lead.telefone:
        sabido.append("Telefone: já informado")

    preenchidos = {
        "intencao": lead.intencao is not None,
        "orcamento": lead.orcamento_min is not None or lead.orcamento_max is not None,
        "localizacao": lead.bairro_interesse is not None
        or lead.regiao_interesse is not None,
        "quartos": lead.quartos is not None,
        "urgencia": lead.urgencia is not None,
    }
    em_aberto = [rotulo for chave, rotulo in LACUNAS if not preenchidos[chave]]

    partes = []
    if sabido:
        partes.append("\n".join(f"- {item}" for item in sabido))
    else:
        partes.append("Você ainda não sabe nada sobre esta pessoa.")

    if em_aberto:
        partes.append(
            "Ainda em aberto: "
            + ", ".join(em_aberto)
            + ". Isto é uma anotação sua, não um roteiro: não pergunte esses "
            "itens em sequência. Deixe que apareçam pela conversa e pela "
            "reação da pessoa aos imóveis que você mostrar."
        )

    partes.append(f"Estágio no funil: {lead.status}.")

    partes.append(texto_dos_compromissos(lead.id))

    return "\n\n".join(partes)


def texto_dos_compromissos(lead_id: int) -> str:
    """O compromisso de pe do lead, em texto para o modelo ler.

    Serve as instrucoes e a tool `listar_agendamentos`, que devolvem a mesma
    verdade em posicoes diferentes da conversa: as instrucoes abrem a
    requisicao, a tool responde no fim dela.

    Nao traz ID. E um compromisso so por pessoa, cobrado por indice unico no
    banco, e as tools de confirmar e cancelar agem sobre ele sem receber qual —
    entao nao ha o que o modelo possa errar nem o que ele precise guardar.

    O que sera visitado tambem nao aparece aqui: mora na `observacoes` do
    compromisso, que e do corretor. A conversa precisa do horario, e e o
    horario que entra.

    O aviso sobre o historico existe porque esta e a verdade do banco agora, e
    o que passou na conversa pode ter mudado desde entao.
    """
    with get_db() as db:
        agendamento = SchedulingService().compromisso_ativo(lead_id, db)
        marcado = (
            (agendamento.tipo, agendamento.data_hora, agendamento.status)
            if agendamento
            else None
        )
    if marcado is None:
        return (
            "Compromisso marcado: nenhum. Se a conversa mencionar algum, ele "
            "foi cancelado ou já aconteceu."
        )

    tipo, quando, status = marcado
    return (
        "Compromisso marcado — é um só, e esta é a verdade do banco agora, "
        f"acima do que a conversa disser:\n- {tipo} em {formatar(quando)} "
        f"({status})"
    )


# As instruções do agente, remontadas a cada turno com o contexto do lead.
#
# Precisa ser `@instructions`, e não `@system_prompt`: o pydantic-ai só insere
# o system prompt quando o `message_history` está vazio (`_agent_graph.py`:
# `if not messages: parts.extend(await self._sys_parts(...))`). Como aqui o
# histórico é reidratado do banco a cada turno, com `system_prompt` o agente
# rodava sem prompt nenhum a partir da segunda mensagem da conversa — sem
# persona, sem regras e sem o contexto do lead. As instruções, ao contrário,
# não moram no histórico: são reaplicadas em todo run.
@sdr_agent.instructions
async def instrucoes_do_agente(ctx: RunContext[SDRDependencies]) -> str:
    """Monta as instruções do turno com o contexto atual do lead."""
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        lead_context = montar_contexto_do_lead(lead)
        ja_respondeu = ctx.deps.lead_service.ja_respondeu(ctx.deps.lead_id, db)
        abertura = "" if ja_respondeu else abertura_da_conversa(lead)
        perfil = (lead.perfil_narrativo if lead else None) or (
            "Ainda não há perfil escrito. Comece um assim que souber algo "
            "que valha a pena o corretor saber."
        )

    instrucoes = SYSTEM_PROMPT.format(
        agora=momento_atual(),
        lead_context=lead_context,
        perfil_narrativo=perfil,
    )
    return instrucoes + abertura


def _registrar_handover(
    lead_id: int,
    channel: str,
    deps: SDRDependencies,
    db,
    ultima_mensagem: str = "",
) -> None:
    """Gera e persiste o resumo executivo ao entregar o lead ao corretor.

    Idempotente: se o handover já foi registrado, não repete nem o resumo nem
    a mensagem (o limite continua estourado em todo turno seguinte).
    """
    if deps.lead_service.has_message_type(lead_id, "handover", db):
        return

    lead = deps.lead_service.get_lead(lead_id, db)
    nota = NOTA_DO_HANDOVER.format(
        mensagem=(ultima_mensagem or "").strip()[:TRECHO_DA_ULTIMA_MENSAGEM]
    )
    deps.lead_service.update_perfil_narrativo(
        lead_id,
        juntar_sem_llm(lead.perfil_narrativo if lead else None, nota),
        db,
    )

    # Depois da nota: o resumo é gerado a partir do perfil, e assim ele já sai
    # sabendo que a conversa terminou por limite.
    resumo = SummaryService().generate_resumo(lead_id, db)
    deps.lead_service.update_qualification(lead_id, {"resumo": resumo}, db)
    # Mesmo encerramento de `encerrar_atendimento`: daqui em diante quem
    # atende é uma pessoa, e um follow-up automático cobrando o próximo dado
    # chegaria por cima dela.
    deps.lead_service.update_status(lead_id, "inativo", db)
    deps.lead_service.save_message(
        lead_id=lead_id,
        channel=channel,
        role="assistant",
        content=HANDOVER_MESSAGE,
        message_type="handover",
        db=db,
    )
    logger.info(
        "event=handover_registrado lead_id=%s channel=%s status=ok",
        lead_id, channel,
    )


def _registrar_turno_bloqueado(
    lead_id: int,
    channel: str,
    qual: str,
    deps: SDRDependencies,
    db,
) -> None:
    """Deixa no histórico o motivo de a pergunta ter ficado sem resposta.

    Sem isto a conversa guarda a mensagem da pessoa e nada depois, e quem lê
    depois — o corretor na ficha, ou nós investigando — vê um agente que
    simplesmente parou de responder, em vez da trava de custo que agiu.

    Vai como `system_notice` e não como resposta do agente: `role="system"`
    fica fora do `build_message_history`, então o modelo não vai reproduzir o
    aviso de indisponibilidade como se fosse fala sua no turno seguinte.
    """
    deps.lead_service.save_message(
        lead_id=lead_id,
        channel=channel,
        role="system",
        content=(
            f"Turno bloqueado: orçamento {qual} de tokens do LLM esgotado. "
            f"A pessoa recebeu o aviso de indisponibilidade."
        ),
        message_type="system_notice",
        db=db,
    )


def _registrar_ferramentas_do_turno(
    result,
    lead_id: int,
    channel: str,
    deps: SDRDependencies,
    db,
) -> None:
    """Persiste as chamadas de ferramenta do turno, com o que elas devolveram.

    Sem isto o agente perde, entre um turno e outro, tudo que as tools lhe
    disseram. Os IDs dos imóveis, por exemplo, só existem no retorno da busca —
    ele nunca os escreve para a pessoa —, então na busca seguinte ele
    reapresentava o mesmo imóvel sem ter como perceber que era o mesmo.

    Guarda o retorno inteiro; quem decide quanto disso volta ao contexto é
    `build_message_history`, que abrevia. Assim a ficha do corretor mantém o
    registro completo do que a ferramenta respondeu sem que o custo do turno
    seguinte cresça na mesma proporção.
    """
    chamadas: dict[str, dict] = {}
    for mensagem in result.new_messages():
        for parte in mensagem.parts:
            if isinstance(parte, ToolCallPart):
                meta = {
                    "tool_name": parte.tool_name,
                    "args": parte.args_as_dict() if parte.args else {},
                    "tool_call_id": parte.tool_call_id,
                }
                # O rastro da busca só existe aqui: as consultas do agente de
                # busca não viram mensagem, então sem isto não há como saber
                # depois de onde saíram os imóveis que a pessoa viu.
                if rastro := deps.rastros_de_busca.get(parte.tool_call_id):
                    meta["busca"] = rastro
                chamadas[parte.tool_call_id] = meta
            elif isinstance(parte, ToolReturnPart):
                meta = chamadas.pop(parte.tool_call_id, None)
                if meta is None:
                    # Retorno sem a chamada correspondente no mesmo run não tem
                    # como ser remontado depois, e um par quebrado faz o
                    # provider recusar a requisição inteira.
                    continue
                deps.lead_service.save_message(
                    lead_id=lead_id,
                    channel=channel,
                    role="tool",
                    content=str(parte.content),
                    message_type="chat",
                    db=db,
                    metadata_json=meta,
                )


async def process_message(
    lead_id: int,
    user_text: str,
    channel: str,
    deps: SDRDependencies,
) -> str:
    """Processa uma mensagem do usuário através do agente SDR."""
    with get_db() as db:
        # O histórico é lido ANTES de persistir a mensagem atual: ela já vai
        # como user_prompt e apareceria duplicada no message_history.
        history = build_message_history(
            deps.lead_service.get_history(lead_id, HISTORY_LIMIT, db)
        )

        deps.lead_service.save_message(
            lead_id=lead_id,
            channel=channel,
            role="user",
            content=user_text,
            message_type="chat",
            db=db,
        )

        # O lead respondeu: entra (ou volta) para o funil ativo. Um lead
        # marcado como inativo pelo follow-up é retomado aqui.
        #
        # Antes do turno, e não depois: durante a execução as tools movem o
        # status (para `qualificado`, `agendado`, ou `inativo` quando o agente
        # encerra o atendimento), e reativar no fim desfaria o que elas
        # acabaram de gravar.
        lead = deps.lead_service.get_lead(lead_id, db)
        if lead and lead.status in ("novo", "inativo"):
            deps.lead_service.update_status(lead_id, "em_qualificacao", db)

        # Check limits
        if deps.llm_usage_service.is_daily_budget_exceeded(db):
            logger.warning(
                "event=budget_diario_estourado lead_id=%s channel=%s "
                "acao=turno_bloqueado",
                lead_id, channel,
            )
            _registrar_turno_bloqueado(lead_id, channel, "diário", deps, db)
            return UNAVAILABLE_MESSAGE

        if deps.llm_usage_service.is_monthly_budget_exceeded(db):
            logger.warning(
                "event=budget_mensal_estourado lead_id=%s channel=%s "
                "acao=turno_bloqueado",
                lead_id, channel,
            )
            _registrar_turno_bloqueado(lead_id, channel, "mensal", deps, db)
            return UNAVAILABLE_MESSAGE

        if deps.llm_usage_service.is_conversation_over_limit(lead_id, db):
            logger.info(
                "event=limite_da_conversa_atingido lead_id=%s channel=%s "
                "acao=handover",
                lead_id, channel,
            )
            _registrar_handover(lead_id, channel, deps, db, user_text)
            return HANDOVER_MESSAGE

    # Run agent
    # O tratamento de falha fica centralizado aqui para que os dois canais
    # (Streamlit e Telegram) degradem da mesma forma, sem vazar erro técnico.
    comeco = time.monotonic()
    try:
        result = await sdr_agent.run(
            user_prompt=user_text,
            deps=deps,
            message_history=history,
            model=build_model(),
        )
    except LLMConfigError as e:
        # Configuração ausente não é falha do provider: nada foi chamado, então
        # não entra na taxa de erro — entraria como ruído permanente enquanto a
        # aplicação estivesse sem configurar.
        logger.error(
            "event=llm_config_error lead_id=%s channel=%s erro=%s",
            lead_id, channel, e,
        )
        return UNAVAILABLE_MESSAGE
    except Exception as e:
        decorrido = _decorrido_ms(comeco)
        logger.exception(
            "event=llm_call_failed lead_id=%s channel=%s tipo_erro=%s "
            "duracao_ms=%s status=erro",
            lead_id, channel, type(e).__name__, decorrido,
        )
        with get_db() as db:
            deps.llm_usage_service.record_failure(
                lead_id=lead_id,
                model=settings.LLM_MODEL,
                operation="chat",
                error_type=type(e).__name__,
                latency_ms=decorrido,
                db=db,
            )
        return UNAVAILABLE_MESSAGE

    latencia_ms = _decorrido_ms(comeco)
    response_text = result.output

    # Record usage and save response
    with get_db() as db:
        # Em pydantic-ai >= 2, `usage` é property (era método nas 0.x).
        usage = result.usage
        tokens_in = usage.input_tokens or 0
        tokens_out = usage.output_tokens or 0

        # Nem todo endpoint OpenAI-compatible devolve o bloco `usage` (o
        # Foundry Local, por exemplo, não devolve). Sem contagem de tokens os
        # budgets diário/mensal nunca disparam, então isso precisa ser visível.
        if not tokens_in and not tokens_out:
            logger.warning(
                "event=usage_ausente lead_id=%s model=%s "
                "detalhe=provider_nao_retornou_tokens impacto=budget_por_token_inativo",
                lead_id, settings.LLM_MODEL,
            )

        deps.llm_usage_service.record(
            lead_id=lead_id,
            model=settings.LLM_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            operation="chat",
            turn=deps.llm_usage_service.get_conversation_turns(lead_id, db) + 1,
            latency_ms=latencia_ms,
            db=db,
        )

        # Antes da resposta do agente, para o histórico sair na ordem em que
        # as coisas aconteceram: a pessoa perguntou, as tools rodaram, ele
        # respondeu.
        _registrar_ferramentas_do_turno(result, lead_id, channel, deps, db)

        # Save assistant response
        deps.lead_service.save_message(
            lead_id=lead_id,
            channel=channel,
            role="assistant",
            content=response_text,
            message_type="chat",
            db=db,
        )

    return response_text
