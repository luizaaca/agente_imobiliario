"""Factory do modelo LLM a partir da configuração de provider.

A POC fala com todos os providers pela API OpenAI-compatible (ADR 0006), então
o que muda entre eles é apenas a base URL. `LLM_PROVIDER` escolhe a base URL
padrão e `OPENAI_BASE_URL`, quando preenchida, sempre tem prioridade.

A construção é preguiçosa (`build_model()` só é chamada no primeiro turno de
conversa) para que importar o pacote não exija credenciais — o dashboard, por
exemplo, precisa rodar sem chave de LLM configurada.
"""

import asyncio
import logging
from typing import Optional
from weakref import WeakKeyDictionary

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.config import settings

logger = logging.getLogger(__name__)

# Base URL padrão por provider. `None` = endpoint padrão do SDK da OpenAI.
DEFAULT_BASE_URLS: dict[str, str | None] = {
    "openai": None,
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
    # 'custom' cobre qualquer endpoint OpenAI-compatible; exige OPENAI_BASE_URL.
    "custom": None,
}

# Providers locais não exigem chave de API.
PROVIDERS_SEM_CHAVE = {"ollama"}


def exige_chave_de_api() -> bool:
    """Se o provider configurado precisa de uma chave para funcionar.

    Publico porque a UI usa isto para avisar na tela, antes de o usuario
    tentar conversar e receber apenas "atendimento indisponivel".
    """
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()
    return provider not in PROVIDERS_SEM_CHAVE


class LLMConfigError(RuntimeError):
    """Configuração de provider LLM inválida ou incompleta."""


def _resolve_base_url(provider: str) -> str | None:
    """Base URL efetiva: a explícita vence a padrão do provider."""
    explicita = (settings.OPENAI_BASE_URL or "").strip()
    if explicita:
        return explicita

    base_url = DEFAULT_BASE_URLS[provider]
    if base_url is None and provider == "custom":
        raise LLMConfigError(
            "LLM_PROVIDER=custom exige OPENAI_BASE_URL preenchida com o "
            "endpoint OpenAI-compatible do seu provedor."
        )
    return base_url


# O cliente HTTP do modelo fica preso ao event loop que o criou. O Streamlit
# abre um loop novo a cada mensagem (asyncio.run), então um cache global único
# quebraria da segunda mensagem em diante com "Event loop is closed". Cachear
# por loop preserva o pooling onde o loop é longevo (bot do Telegram) e entrega
# um cliente válido a cada loop efêmero; a entrada morre junto com o loop.
_modelos_por_loop: WeakKeyDictionary = WeakKeyDictionary()
_modelo_sem_loop: Optional[OpenAIChatModel] = None


def build_model() -> OpenAIChatModel:
    """Devolve o modelo configurado, válido para o event loop corrente.

    Raises:
        LLMConfigError: provider desconhecido ou configuração incompleta.
    """
    global _modelo_sem_loop

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        if _modelo_sem_loop is None:
            _modelo_sem_loop = _construir_modelo()
        return _modelo_sem_loop

    modelo = _modelos_por_loop.get(loop)
    if modelo is None:
        modelo = _construir_modelo()
        _modelos_por_loop[loop] = modelo
    return modelo


def _construir_modelo() -> OpenAIChatModel:
    """Constrói o modelo configurado, validando a configuração."""
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()

    if provider not in DEFAULT_BASE_URLS:
        suportados = ", ".join(sorted(DEFAULT_BASE_URLS))
        raise LLMConfigError(
            f"LLM_PROVIDER='{provider}' não é suportado. "
            f"Valores aceitos: {suportados}."
        )

    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key and provider not in PROVIDERS_SEM_CHAVE:
        raise LLMConfigError(
            f"OPENAI_API_KEY não configurada — obrigatória para "
            f"LLM_PROVIDER='{provider}'. Preencha no .env."
        )

    base_url = _resolve_base_url(provider)

    provider_kwargs: dict[str, str] = {
        # O SDK da OpenAI exige uma chave não vazia mesmo em endpoints locais.
        "api_key": api_key or "no-key-required",
    }
    if base_url:
        provider_kwargs["base_url"] = base_url

    logger.info(
        "LLM configurado: provider=%s model=%s base_url=%s",
        provider,
        settings.LLM_MODEL,
        base_url or "(padrão OpenAI)",
    )
    return OpenAIChatModel(
        settings.LLM_MODEL,
        provider=OpenAIProvider(**provider_kwargs),
    )
