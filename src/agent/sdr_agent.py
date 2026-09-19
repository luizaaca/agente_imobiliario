"""Agente SDR Imobiliário principal usando PydanticAI."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Optional

from pydantic import Field
from pydantic_ai import Agent, RunContext

from src.agent.history import HISTORY_LIMIT, build_message_history
from src.agent.prompts import HANDOVER_MESSAGE, SYSTEM_PROMPT, UNAVAILABLE_MESSAGE
from src.agent.provider import LLMConfigError, build_model
from src.config import settings
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.services.summary_service import SummaryService

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


# Create the agent
# Nem o modelo nem o system prompt são fixados aqui:
# - o modelo vem de build_model() no momento do run, para que importar este
#   módulo não exija credenciais de LLM (o dashboard roda sem elas);
# - o system prompt é montado a cada run pelo @sdr_agent.system_prompt abaixo,
#   que injeta o contexto atual do lead no template.
sdr_agent = Agent(
    deps_type=SDRDependencies,
    retries=2,
)


# Register tools using @sdr_agent.tool decorator
# Each tool receives RunContext[SDRDependencies] as first arg

@sdr_agent.tool
async def buscar_imoveis(
    ctx: RunContext[SDRDependencies],
    intencao: Optional[str] = None,
    orcamento_min: Optional[float] = None,
    orcamento_max: Optional[float] = None,
    regiao_interesse: Optional[str] = None,
    bairro_interesse: Optional[str] = None,
    quartos: Optional[int] = None,
    termos_livres: Optional[str] = None,
    limite_resultados: int = 5,
) -> str:
    """Buscar imóveis no catálogo com filtros estruturados e ranking textual."""
    logger.info(f"Tool buscar_imoveis chamada para lead {ctx.deps.lead_id}")
    with get_db() as db:
        results = ctx.deps.catalog_service.search(
            intencao=intencao,
            orcamento_min=orcamento_min,
            orcamento_max=orcamento_max,
            regiao_interesse=regiao_interesse,
            bairro_interesse=bairro_interesse,
            quartos=quartos,
            termos_livres=termos_livres,
            limite=limite_resultados,
            db=db,
        )
        if not results:
            return "Nenhum imóvel encontrado com os critérios informados."
        
        output_lines = [f"Encontrei {len(results)} imóvel(is):"]
        for r in results:
            descricao = (r.descricao or "")[:200]
            output_lines.append(
                f"\n- **{r.titulo}** (ID: {r.id})\n"
                f"  Tipo: {r.tipo} | {r.operacao}\n"
                f"  Bairro: {r.bairro} ({r.zona})\n"
                f"  Preço: R$ {r.preco:,.2f}\n"
                f"  Quartos: {r.quartos} | Suítes: {r.suites or 0} | Área: {r.area_m2}m²\n"
                f"  {descricao}..."
            )
        return "\n".join(output_lines)


@sdr_agent.tool
async def registrar_qualificacao(
    ctx: RunContext[SDRDependencies],
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
    logger.info(f"Tool registrar_qualificacao chamada para lead {ctx.deps.lead_id}")
    data = {k: v for k, v in locals().items() if k != 'ctx' and v is not None}
    with get_db() as db:
        lead = ctx.deps.lead_service.update_qualification(ctx.deps.lead_id, data, db)
        # Recalculate score
        score = ctx.deps.lead_service.calculate_score(ctx.deps.lead_id, db)
        return f"Lead atualizado com sucesso. Score atual: {score}"


@sdr_agent.tool
async def atualizar_perfil_lead(
    ctx: RunContext[SDRDependencies],
    perfil_narrativo_atualizado: str,
    motivo_atualizacao: Optional[str] = None,
) -> str:
    """Atualizar o perfil narrativo textual do lead com novas informações."""
    logger.info(f"Tool atualizar_perfil_lead chamada para lead {ctx.deps.lead_id}")
    with get_db() as db:
        ctx.deps.lead_service.update_perfil_narrativo(
            ctx.deps.lead_id, perfil_narrativo_atualizado, db
        )
        return "Perfil narrativo atualizado com sucesso."


@sdr_agent.tool
async def agendar_reuniao(
    ctx: RunContext[SDRDependencies],
    tipo: Annotated[str, Field(description="Exatamente um de: visita, reuniao.")],
    data_hora: Annotated[str, Field(description="Data e hora no formato YYYY-MM-DD HH:MM.")],
    observacoes: Optional[str] = None,
    imovel_id: Annotated[Optional[int], Field(description=(
        "ID de um imóvel devolvido por `buscar_imoveis`, quando a visita for a "
        "um imóvel específico. Não invente: use apenas IDs já apresentados."))] = None,
) -> str:
    """Registrar visita ou reunião para handover ao corretor."""
    logger.info(f"Tool agendar_reuniao chamada para lead {ctx.deps.lead_id}")
    if tipo not in ("visita", "reuniao"):
        return "Tipo inválido. Use 'visita' ou 'reuniao'."
    try:
        dt = datetime.strptime(data_hora, "%Y-%m-%d %H:%M")
    except ValueError:
        return "Formato de data inválido. Use YYYY-MM-DD HH:MM."

    with get_db() as db:
        imovel = None
        if imovel_id is not None:
            # Um ID inventado violaria a FK e derrubaria o turno inteiro. O
            # erro volta como texto para o modelo poder se corrigir sozinho.
            imovel = ctx.deps.catalog_service.get_by_id(imovel_id, db)
            if imovel is None:
                logger.warning(
                    "event=imovel_inexistente_no_agendamento lead_id=%s imovel_id=%s",
                    ctx.deps.lead_id, imovel_id,
                )
                return (
                    f"Imóvel {imovel_id} não existe no catálogo. Use um ID "
                    f"retornado por `buscar_imoveis` ou agende sem imóvel."
                )

        agendamento = ctx.deps.scheduling_service.create(
            lead_id=ctx.deps.lead_id,
            tipo=tipo,
            data_hora=dt,
            observacoes=observacoes,
            imovel_id=imovel_id,
            db=db,
        )
        linha_imovel = f"\nImóvel: {imovel.titulo} (ID: {imovel.id})" if imovel else ""
        return (
            f"Agendamento criado com sucesso! (ID: {agendamento.id})\n"
            f"Tipo: {tipo}\n"
            f"Data/Hora: {data_hora}{linha_imovel}\n"
            f"Status: pendente"
        )


@sdr_agent.tool
async def gerar_resumo_corretor(
    ctx: RunContext[SDRDependencies],
) -> str:
    """Gerar briefing executivo para o corretor."""
    logger.info(f"Tool gerar_resumo_corretor chamada para lead {ctx.deps.lead_id}")
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        if not lead:
            return "Lead não encontrado."
        messages = ctx.deps.lead_service.get_history(ctx.deps.lead_id, 50, db)

        nome = lead.nome or f"Lead {lead.id}"
        intencao = lead.intencao or "não informada"
        orc_min = lead.orcamento_min or "?"
        orc_max = lead.orcamento_max or "?"
        regiao = lead.regiao_interesse or lead.bairro_interesse or "não informada"
        quartos = lead.quartos or "não informado"
        urgencia = lead.urgencia or "não informada"
        score = lead.score or "não calculado"
        perfil_nar = lead.perfil_narrativo or "Ainda não construído."
        total_msgs = len(messages)
        user_msgs = sum(1 for m in messages if m.role == "user")

        resumo = (
            f"## Resumo Executivo — {nome}\n\n"
            f"### Perfil\n"
            f"- Intenção: {intencao}\n"
            f"- Orçamento: R$ {orc_min} a R$ {orc_max}\n"
            f"- Região: {regiao}\n"
            f"- Quartos: {quartos}\n"
            f"- Urgência: {urgencia}\n"
            f"- Score: {score}/10\n"
            f"- Status: {lead.status}\n\n"
            f"### Perfil Narrativo\n{perfil_nar}\n\n"
            f"### Histórico ({total_msgs} mensagens)\n"
            f"Conversa ativa com {user_msgs} mensagens do lead.\n\n"
            f"### Próximos Passos\n"
            f"Baseado no score e perfil, o corretor deve priorizar o contato."
        )

        # Save resumo to lead
        ctx.deps.lead_service.update_qualification(
            ctx.deps.lead_id, {"resumo": resumo}, db
        )
        return resumo


# Dynamic system prompt
@sdr_agent.system_prompt
async def dynamic_system_prompt(ctx: RunContext[SDRDependencies]) -> str:
    """Gera o system prompt dinâmico com contexto do lead."""
    with get_db() as db:
        lead = ctx.deps.lead_service.get_lead(ctx.deps.lead_id, db)
        if lead:
            lead_context = (
                f"Nome: {lead.nome or 'Não informado'}\n"
                f"Status: {lead.status}\n"
                f"Intenção: {lead.intencao or 'Não informada'}\n"
                f"Orçamento: R$ {lead.orcamento_min or '?'} a R$ {lead.orcamento_max or '?'}\n"
                f"Região: {lead.regiao_interesse or 'Não informada'}\n"
                f"Bairro: {lead.bairro_interesse or 'Não informado'}\n"
                f"Quartos: {lead.quartos or 'Não informado'}\n"
                f"Urgência: {lead.urgencia or 'Não informada'}\n"
                f"Score: {lead.score or 'N/A'}"
            )
            perfil = lead.perfil_narrativo or "Nenhum perfil construído ainda."
        else:
            lead_context = "Lead novo, sem dados coletados."
            perfil = "Nenhum perfil construído ainda."

    return SYSTEM_PROMPT.format(
        lead_context=lead_context,
        perfil_narrativo=perfil,
    )


def _registrar_handover(
    lead_id: int,
    channel: str,
    deps: SDRDependencies,
    db,
) -> None:
    """Gera e persiste o resumo executivo ao entregar o lead ao corretor.

    Idempotente: se o handover já foi registrado, não repete nem o resumo nem
    a mensagem (o limite continua estourado em todo turno seguinte).
    """
    if deps.lead_service.has_message_type(lead_id, "handover", db):
        return

    resumo = SummaryService().generate_resumo(lead_id, db)
    deps.lead_service.update_qualification(lead_id, {"resumo": resumo}, db)
    deps.lead_service.save_message(
        lead_id=lead_id,
        channel=channel,
        role="assistant",
        content=HANDOVER_MESSAGE,
        message_type="handover",
        db=db,
    )
    logger.info(f"Handover registrado para o lead {lead_id}; resumo persistido.")


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

        # Check limits
        if deps.llm_usage_service.is_daily_budget_exceeded(db):
            logger.warning("Budget diário de LLM atingido!")
            return UNAVAILABLE_MESSAGE

        if deps.llm_usage_service.is_monthly_budget_exceeded(db):
            logger.warning("Budget mensal de LLM atingido!")
            return UNAVAILABLE_MESSAGE

        if deps.llm_usage_service.is_conversation_over_limit(lead_id, db):
            logger.info(f"Lead {lead_id} atingiu limite de conversa. Fazendo handover.")
            _registrar_handover(lead_id, channel, deps, db)
            return HANDOVER_MESSAGE

    # Run agent
    # O tratamento de falha fica centralizado aqui para que os dois canais
    # (Streamlit e Telegram) degradem da mesma forma, sem vazar erro técnico.
    try:
        result = await sdr_agent.run(
            user_prompt=user_text,
            deps=deps,
            message_history=history,
            model=build_model(),
        )
    except LLMConfigError as e:
        logger.error(
            "event=llm_config_error lead_id=%s channel=%s erro=%s",
            lead_id, channel, e,
        )
        return UNAVAILABLE_MESSAGE
    except Exception as e:
        logger.exception(
            "event=llm_call_failed lead_id=%s channel=%s tipo_erro=%s",
            lead_id, channel, type(e).__name__,
        )
        return UNAVAILABLE_MESSAGE

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
            db=db,
        )

        # Save assistant response
        deps.lead_service.save_message(
            lead_id=lead_id,
            channel=channel,
            role="assistant",
            content=response_text,
            message_type="chat",
            db=db,
        )

        # O lead respondeu: entra (ou volta) para o funil ativo. Um lead
        # marcado como inativo pelo follow-up é retomado aqui.
        lead = deps.lead_service.get_lead(lead_id, db)
        if lead and lead.status in ("novo", "inativo"):
            deps.lead_service.update_status(lead_id, "em_qualificacao", db)

    return response_text
