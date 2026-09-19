#!/usr/bin/env python3
"""Ponto de entrada do Bot Telegram + Scheduler de follow-up.

Processo 2: roda o bot com Long Polling e o scheduler APScheduler.
"""

import asyncio
import logging

from src.channels.telegram_bot import create_telegram_app
from src.config import settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN não configurado no .env")
        return
    
    logger.info("Iniciando Bot Telegram + Scheduler...")
    app = create_telegram_app()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
