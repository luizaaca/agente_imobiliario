"""Agente SDR Imobiliário principal usando PydanticAI."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic_ai import Agent, RunContext

from src.agent.prompts import SYSTEM_PROMPT, HANDOVER_MESSAGE, UNAVAILABLE_MESSAGE
from src.config import settings
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.scheduling_service import SchedulingService
from src.services.llm_usage_service import LLMUsageService

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
sdr_agent = Agent(
    model=f"openai:{settings.LLM_MODEL}",
    system_prompt=SYSTEM_PROMPT,  # Will be dynamically formatted
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
            output_lines.append(
                f"\n- **{r.titulo}** (ID: {r.id})\n"
                f"  Tipo: {r.tipo} | {r.operacao}\n"
                f"  Bairro: {r.bairro} ({r.zona})\n"
                f"  Preço: R$ {r.preco:,.2f}\n"
                f"  Quartos: {r.quartos} | Suítes: {r.suites or 0} | Área: {r.area_m2}m²\n"
                f"  {r.descricao[:200]}..."
            )
        return "\n".join(output_lines)


@sdr_agent.tool
async def registrar_qualificacao(
    ctx: RunContext[SDRDependencies],
    intencao: Optional[str] = None,
    perfil: Optional[str] = None,
    orcamento_min: Optional[float] = None,
    orcamento_max: Optional[float] = None,
    bairro_interesse: Optional[str] = None,
    regiao_interesse: Optional[str] = None,
    quartos: Optional[int] = None,
    urgencia: Optional[str] = None,
    motivo_busca: Optional[str] = None,
    forma_pagamento: Optional[str] = None,
    amenidades_desejadas: Optional[str] = None,
    tipologia_interesse: Optional[str] = None,
) -> str:
    """Registrar ou atualizar dados de qualificação estruturados do lead."""
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
    tipo: str,
    data_hora: str,
    observacoes: Optional[str] = None,
    imovel_id: Optional[int] = None,
) -> str:
    """Registrar visita ou reunião para handover ao corretor."""
    logger.info(f"Tool agendar_reuniao chamada para lead {ctx.deps.lead_id}")
    try:
        dt = datetime.strptime(data_hora, "%Y-%m-%d %H:%M")
    except ValueError:
        return "Formato de data inválido. Use YYYY-MM-DD HH:MM."
    
    with get_db() as db:
        agendamento = ctx.deps.scheduling_service.create(
            lead_id=ctx.deps.lead_id,
            tipo=tipo,
            data_hora=dt,
            observacoes=observacoes,
            db=db,
        )
        return (
            f"Agendamento criado com sucesso!\n"
            f"Tipo: {tipo}\n"
            f"Data/Hora: {data_hora}\n"
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


async def process_message(
    lead_id: int,
    user_text: str,
    channel: str,
    deps: SDRDependencies,
) -> str:
    """Processa uma mensagem do usuário através do agente SDR."""
    # Save user message
    with get_db() as db:
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

        if deps.llm_usage_service.is_conversation_over_limit(lead_id, db):
            logger.info(f"Lead {lead_id} atingiu limite de conversa. Fazendo handover.")
            return HANDOVER_MESSAGE

    # Run agent
    result = await sdr_agent.run(
        user_prompt=user_text,
        deps=deps,
    )

    response_text = result.data

    # Record usage and save response
    with get_db() as db:
        usage = result.usage()
        deps.llm_usage_service.record(
            lead_id=lead_id,
            model=settings.LLM_MODEL,
            tokens_in=usage.request_tokens or 0,
            tokens_out=usage.response_tokens or 0,
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

        # Update lead status if still novo
        lead = deps.lead_service.get_lead(lead_id, db)
        if lead and lead.status == "novo":
            deps.lead_service.update_status(lead_id, "em_qualificacao", db)

    return response_text
