"""Factory do modelo LLM a partir da configuração de provider.

A POC fala com todos os providers pela API OpenAI-compatible (ADR 0006), então
o que muda entre eles é apenas a base URL. `LLM_PROVIDER` escolhe a base URL
padrão e `OPENAI_BASE_URL`, quando preenchida, sempre tem prioridade.

A construção é preguiçosa (`build_model()` só é chamada no primeiro turno de
conversa) para que importar o pacote não exija credenciais — o dashboard, por
exemplo, precisa rodar sem chave de LLM configurada.
"""

import logging
from functools import lru_cache

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
_PROVIDERS_SEM_CHAVE = {"ollama"}


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


@lru_cache(maxsize=1)
def build_model() -> OpenAIChatModel:
    """Constrói o modelo configurado, validando a configuração.

    Raises:
        LLMConfigError: provider desconhecido ou configuração incompleta.
    """
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()

    if provider not in DEFAULT_BASE_URLS:
        suportados = ", ".join(sorted(DEFAULT_BASE_URLS))
        raise LLMConfigError(
            f"LLM_PROVIDER='{provider}' não é suportado. "
            f"Valores aceitos: {suportados}."
        )

    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key and provider not in _PROVIDERS_SEM_CHAVE:
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
