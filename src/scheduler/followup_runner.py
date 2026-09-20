"""Orquestração de um ciclo de follow-up automático.

Vive na camada de scheduler porque é o único ponto que combina domínio
(FollowUpService, LeadService) com agente (geração via LLM) e canal (envio).
Manter essa costura aqui evita que os services dependam do agente.

Um ciclo, para cada lead elegível:
  1. monta o contexto do lead;
  2. gera a mensagem contextual da régua via LLM;
  3. persiste a Mensagem (message_type='followup');
  4. registra o consumo de LLM (operation='followup');
  5. despacha pelo canal, quando há remetente disponível;
  6. registra o FollowUpAttempt com o desfecho;
  7. marca o lead como inativo se a régua de silêncio se esgotou.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.agent.followup_agent import gerar_mensagem_followup
from src.agent.provider import LLMConfigError
from src.config import settings
from src.db.session import get_db
from src.services.followup_service import REGUAS, FollowUpService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)


class Sender(Protocol):
    """Despacha uma mensagem de follow-up pelo canal do lead.

    Deve devolver True quando a mensagem saiu de fato. Um canal sem envio
    ativo (Streamlit, por exemplo) simplesmente não é registrado como sender.
    """

    async def __call__(self, channel: str, external_chat_id: str, texto: str) -> bool:
        ...


def _montar_contexto(lead, regua: str, db) -> dict[str, object]:
    """Reúne, ainda dentro da sessão, tudo que a geração precisa."""
    lead_service = LeadService()

    historico = lead_service.get_history(lead.id, 4, db)
    ultima = historico[-1].content[:300] if historico else None

    contexto: dict[str, object] = {
        "nome": lead.nome,
        "intencao": lead.intencao,
        "orcamento_max": lead.orcamento_max,
        "bairro_interesse": lead.bairro_interesse,
        "regiao_interesse": lead.regiao_interesse,
        "quartos": lead.quartos,
        "urgencia": lead.urgencia,
        "motivo_busca": lead.motivo_busca,
        "perfil_narrativo": lead.perfil_narrativo,
        "ultima_mensagem": ultima,
    }

    if regua == "pos_agendamento":
        agendamentos = SchedulingService().list_by_lead(lead.id, db)
        proximo = next(
            (a for a in reversed(agendamentos) if a.status in ("pendente", "confirmado")),
            None,
        )
        if proximo:
            contexto["agendamento"] = (
                f"{proximo.tipo} em {proximo.data_hora:%d/%m/%Y às %H:%M} "
                f"(status: {proximo.status})"
            )

    return contexto


async def run_followup_cycle(sender: Optional[Sender] = None) -> dict[str, int]:
    """Executa um ciclo completo de follow-up.

    Returns:
        Contadores do ciclo: elegiveis, enviados, gerados, falhas, inativados.
    """
    stats = {"elegiveis": 0, "enviados": 0, "gerados": 0, "falhas": 0, "inativados": 0}

    followup_service = FollowUpService()
    usage_service = LLMUsageService()

    with get_db() as db:
        # O budget é checado uma vez por ciclo: se o teto já estourou, nem vale
        # começar a gerar mensagens.
        if usage_service.is_daily_budget_exceeded(db):
            logger.warning("event=followup_abortado motivo=budget_diario_excedido")
            return stats
        if usage_service.is_monthly_budget_exceeded(db):
            logger.warning("event=followup_abortado motivo=budget_mensal_excedido")
            return stats

        elegiveis = [
            (lead.id, lead.canal_origem, regua, _montar_contexto(lead, regua, db))
            for lead, regua in followup_service.get_eligible_leads(db)
        ]

    stats["elegiveis"] = len(elegiveis)

    for lead_id, canal_origem, regua, contexto in elegiveis:
        await _processar_lead(lead_id, canal_origem, regua, contexto, sender, stats)

    logger.info("event=followup_ciclo_concluido %s", stats)
    return stats


@dataclass
class DisparoManual:
    """Desfecho de um follow-up disparado pelo corretor na tela."""

    executado: bool
    motivo: str = ""
    stats: dict[str, int] = field(default_factory=dict)


async def run_followup_para_lead(
    lead_id: int, sender: Optional[Sender] = None
) -> DisparoManual:
    """Dispara o follow-up de um lead só, a pedido do corretor.

    Mesma lógica do ciclo automático, gatilho diferente: o que se dispensa é
    apenas a janela de inatividade, que existe para o robô não ser inoportuno
    — o corretor, olhando o lead, já decidiu que é hora.

    O teto de tentativas da régua e o budget continuam valendo: são limites de
    custo e de insistência, não de tempo, e valem igual em qualquer gatilho.
    """
    stats = {"elegiveis": 0, "enviados": 0, "gerados": 0, "falhas": 0, "inativados": 0}
    followup_service = FollowUpService()
    usage_service = LLMUsageService()

    with get_db() as db:
        if usage_service.is_daily_budget_exceeded(db):
            return DisparoManual(False, "O orçamento diário de LLM já foi atingido.")
        if usage_service.is_monthly_budget_exceeded(db):
            return DisparoManual(False, "O orçamento mensal de LLM já foi atingido.")

        lead = LeadService().get_lead(lead_id, db)
        if lead is None:
            return DisparoManual(False, "Lead não encontrado.")

        regua = followup_service.regua_do_status(lead.status)
        if regua is None:
            return DisparoManual(
                False, f"Não há régua de follow-up para o status `{lead.status}`."
            )

        tentativas = followup_service.get_attempts_count(lead_id, regua, db)
        maximo = REGUAS[regua]["max_tentativas"]
        if tentativas >= maximo:
            return DisparoManual(
                False,
                f"A régua *{REGUAS[regua]['descricao']}* já esgotou as "
                f"{maximo} tentativas deste lead.",
            )

        canal_origem = lead.canal_origem
        contexto = _montar_contexto(lead, regua, db)

    stats["elegiveis"] = 1
    logger.info(
        "event=followup_disparo_manual lead_id=%s regua=%s tentativa=%s",
        lead_id, regua, tentativas + 1,
    )
    await _processar_lead(lead_id, canal_origem, regua, contexto, sender, stats)
    return DisparoManual(True, "", stats)


async def _processar_lead(
    lead_id: int,
    canal_origem: Optional[str],
    regua: str,
    contexto: dict[str, object],
    sender: Optional[Sender],
    stats: dict[str, int],
) -> None:
    """Gera, persiste, despacha e registra o follow-up de um lead.

    Extraido do ciclo para que o disparo manual do dashboard passe exatamente
    pelo mesmo caminho: mesma geracao, mesma persistencia, mesmo registro de
    tentativa. O que muda entre os dois e so quem escolhe o lead.
    """
    followup_service = FollowUpService()
    lead_service = LeadService()
    usage_service = LLMUsageService()

    try:
        with get_db() as db:
            tentativa = followup_service.get_attempts_count(lead_id, regua, db) + 1

        gerado = await gerar_mensagem_followup(contexto, regua, tentativa)
        if not gerado.texto:
            raise ValueError("LLM devolveu mensagem vazia")

        with get_db() as db:
            identidade = lead_service.get_primary_identity(lead_id, db)
            canal = identidade.channel if identidade else (canal_origem or "desconhecido")
            chat_id = identidade.external_chat_id if identidade else None

            msg = lead_service.save_message(
                lead_id=lead_id,
                channel=canal,
                role="assistant",
                content=gerado.texto,
                message_type="followup",
                db=db,
                status="generated",
            )
            message_id = msg.id

            usage_service.record(
                lead_id=lead_id,
                model=settings.LLM_MODEL,
                tokens_in=gerado.tokens_in,
                tokens_out=gerado.tokens_out,
                operation="followup",
                db=db,
            )

        enviado = False
        motivo_falha: Optional[str] = None
        if sender and chat_id:
            try:
                enviado = await sender(canal, chat_id, gerado.texto)
                if not enviado:
                    motivo_falha = "canal recusou o envio"
            except Exception as e:
                motivo_falha = f"{type(e).__name__}: {e}"[:120]
                logger.exception(
                    "event=followup_envio_falhou lead_id=%s canal=%s", lead_id, canal
                )
        elif not sender:
            motivo_falha = "sem remetente ativo para o canal"

        with get_db() as db:
            if enviado:
                lead_service.mark_message_sent(message_id, db)
                status_tentativa = "sent"
                stats["enviados"] += 1
            else:
                # A mensagem existe e aparece no painel do corretor mesmo
                # sem despacho ativo — isso não é uma falha de geração.
                status_tentativa = "failed" if chat_id and sender else "generated"
                stats["gerados" if status_tentativa == "generated" else "falhas"] += 1

            followup_service.record_attempt(
                lead_id=lead_id,
                regua=regua,
                status=status_tentativa,
                db=db,
                message_id=message_id,
                failure_reason=motivo_falha,
            )

            if followup_service.deve_marcar_inativo(lead_id, regua, db):
                lead_service.update_status(lead_id, "inativo", db)
                stats["inativados"] += 1
                logger.info(
                    "event=lead_inativado lead_id=%s regua=%s "
                    "motivo=tentativas_esgotadas", lead_id, regua,
                )

        logger.info(
            "event=followup_processado lead_id=%s regua=%s tentativa=%s enviado=%s",
            lead_id, regua, tentativa, enviado,
        )

    except LLMConfigError as e:
        logger.error("event=followup_llm_config_error lead_id=%s erro=%s", lead_id, e)
        stats["falhas"] += 1
    except Exception as e:
        stats["falhas"] += 1
        logger.exception(
            "event=followup_falhou lead_id=%s regua=%s tipo_erro=%s",
            lead_id, regua, type(e).__name__,
        )
        with get_db() as db:
            followup_service.record_attempt(
                lead_id=lead_id, regua=regua, status="failed", db=db,
                failure_reason=f"{type(e).__name__}: {e}"[:120],
            )
