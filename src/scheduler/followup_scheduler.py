"""Scheduler de follow-up automático com APScheduler."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.db.session import get_db
from src.services.followup_service import FollowUpService

logger = logging.getLogger(__name__)

def create_scheduler() -> AsyncIOScheduler:
    """Cria e configura o scheduler de follow-up."""
    scheduler = AsyncIOScheduler()
    
    @scheduler.scheduled_job('interval', minutes=30, id='followup_job')
    async def run_followup():
        logger.info("Executando job de follow-up automático...")
        with get_db() as db:
            followup_service = FollowUpService()
            eligible = followup_service.get_eligible_leads(db)
            logger.info(f"Leads elegíveis para follow-up: {len(eligible)}")
            for lead in eligible:
                try:
                    # Determine regua and generate follow-up
                    regua = followup_service.determine_regua(lead, db)
                    if regua:
                        logger.info(f"Processando follow-up para lead {lead.id}, régua: {regua}")
                        # Follow-up generation would happen here
                except Exception as e:
                    logger.error(f"Erro no follow-up do lead {lead.id}: {e}")
    
    return scheduler
