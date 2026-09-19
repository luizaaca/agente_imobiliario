"""Adaptador Telegram: handlers e despacho para o agente SDR."""

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.agent.sdr_agent import SDRDependencies, process_message
from src.config import settings
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para /start: saudação e criação do lead."""
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    with get_db() as db:
        LeadService().get_or_create_lead(
            channel="telegram",
            external_id=chat_id,
            db=db,
            nome=user.full_name if user else None,
        )
    
    await update.message.reply_text(
        f"Olá{f', {user.first_name}' if user else ''}! 🏠\n\n"
        "Sou o assistente digital da imobiliária. "
        "Posso ajudar você a encontrar o imóvel ideal!\n\n"
        "Me conta: você está procurando imóvel para comprar, "
        "alugar ou investir? 😊"
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para mensagens de texto."""
    chat_id = str(update.effective_chat.id)
    user_text = update.message.text
    
    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)
    
    with get_db() as db:
        lead_service = LeadService()
        lead = lead_service.get_or_create_lead(
            channel="telegram",
            external_id=chat_id,
            db=db,
        )
        lead_id = lead.id
    
    deps = SDRDependencies(
        lead_id=lead_id,
        channel="telegram",
        lead_service=LeadService(),
        catalog_service=CatalogService(),
        scheduling_service=SchedulingService(),
        llm_usage_service=LLMUsageService(),
    )
    
    try:
        response = await process_message(
            lead_id=lead_id,
            user_text=user_text,
            channel="telegram",
            deps=deps,
        )
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Erro ao processar mensagem do lead {lead_id}: {e}")
        await update.message.reply_text(
            "Desculpe, tive um problema ao processar sua mensagem. "
            "Pode tentar novamente? 🙏"
        )


def make_sender(app: Application):
    """Cria o despachante de follow-up ligado a esta aplicação Telegram."""

    async def send(channel: str, external_chat_id: str, texto: str) -> bool:
        if channel != "telegram":
            # Outros canais (Streamlit) não têm envio ativo: a mensagem fica
            # persistida e aparece no painel.
            return False
        await app.bot.send_message(chat_id=external_chat_id, text=texto)
        return True

    return send


def create_telegram_app() -> Application:
    """Cria e configura a aplicação Telegram."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot Telegram configurado com sucesso.")
    return app
