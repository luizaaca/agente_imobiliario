#!/usr/bin/env python3
"""Ponto de entrada do Bot Telegram + Scheduler de follow-up.

Processo 2: roda o bot com Long Polling e o scheduler APScheduler no mesmo
event loop. O scheduler sobe no `post_init` porque o AsyncIOScheduler precisa
do loop que o python-telegram-bot cria — iniciá-lo antes de `run_polling()`
o prenderia a um loop que nunca roda.
"""

import logging

from telegram.ext import Application

from src.channels.telegram_bot import create_telegram_app, make_sender
from src.config import settings
from src.scheduler.followup_scheduler import create_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _start_scheduler(app: Application) -> None:
    scheduler = create_scheduler(sender=make_sender(app))
    scheduler.start()
    # Guardado para o shutdown e para inspeção em runtime.
    app.bot_data["scheduler"] = scheduler
    logger.info("Scheduler de follow-up iniciado junto ao bot.")


async def _stop_scheduler(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler de follow-up encerrado.")


def main():
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN não configurado no .env")
        return

    logger.info("Iniciando Bot Telegram + Scheduler...")
    app = create_telegram_app()
    app.post_init = _start_scheduler
    app.post_shutdown = _stop_scheduler
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
