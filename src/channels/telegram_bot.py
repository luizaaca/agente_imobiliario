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
    """Handler para /start: cria o lead e delega ao agente.

    O /start não carrega texto do usuário, então usamos uma saudação
    sintética para que o agente gere a primeira resposta via LLM — com
    tom, persona e contexto adequados — em vez de uma mensagem fixa.
    """
    chat_id = str(update.effective_chat.id)
    user = update.effective_user

    # Garante a criação do lead com o nome do usuário antes de delegar;
    # o message_handler chamaria get_or_create_lead também, mas sem o nome.
    with get_db() as db:
        LeadService().get_or_create_lead(
            channel="telegram",
            external_id=chat_id,
            db=db,
            nome=user.full_name if user else None,
        )

    # Injeta o texto sintético no update e delega ao fluxo normal.
    update.message.text = "Oi"
    await message_handler(update, context)


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
        logger.exception(
            "event=mensagem_nao_processada lead_id=%s channel=telegram "
            "status=erro tipo_erro=%s",
            lead_id, type(e).__name__,
        )
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

    logger.info("event=telegram_bot_configurado status=ok")
    return app
