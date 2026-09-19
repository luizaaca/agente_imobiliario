"""Scheduler de follow-up automático com APScheduler."""

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.scheduler.followup_runner import Sender, run_followup_cycle

logger = logging.getLogger(__name__)

# Intervalo entre ciclos. Configurável para permitir demonstrar o cenário de
# follow-up sem esperar meia hora.
INTERVALO_MINUTOS = int(os.getenv("FOLLOWUP_INTERVAL_MINUTES", "30"))


def create_scheduler(sender: Optional[Sender] = None) -> AsyncIOScheduler:
    """Cria e configura o scheduler de follow-up.

    Args:
        sender: despachante do canal. Sem ele, as mensagens são geradas e
            persistidas, mas não saem para o lead.
    """
    scheduler = AsyncIOScheduler()

    async def run_followup():
        logger.info("Executando job de follow-up automático...")
        await run_followup_cycle(sender=sender)

    scheduler.add_job(
        run_followup,
        "interval",
        minutes=INTERVALO_MINUTOS,
        id="followup_job",
        # Duas execuções simultâneas gerariam follow-up duplicado; a constraint
        # do banco é a última linha de defesa, esta é a primeira.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    logger.info(
        "Scheduler de follow-up configurado: 1 ciclo a cada %s min.",
        INTERVALO_MINUTOS,
    )
    return scheduler
