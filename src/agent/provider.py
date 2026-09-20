"""Factory do modelo LLM a partir da configuração de provider.

A POC fala com todos os providers pela API OpenAI-compatible (ADR 0006), então
o que muda entre eles é apenas a base URL. `LLM_PROVIDER` escolhe a base URL
padrão e `LLM_BASE_URL`, quando preenchida, sempre tem prioridade.

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

# Base URL padrão por provider.
#
# `openai` traz a URL explícita, e não `None`, porque o SDK da OpenAI lê
# `OPENAI_BASE_URL` do ambiente quando não recebe `base_url`. Uma variável
# solta no ambiente redirecionaria as chamadas sem nada no código dizer isso.
# Passando sempre, o destino é determinado só pela configuração da aplicação.
DEFAULT_BASE_URLS: dict[str, str | None] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
    # 'custom' cobre qualquer endpoint OpenAI-compatible; exige LLM_BASE_URL.
    "custom": None,
}

# Providers locais não exigem chave de API.
PROVIDERS_SEM_CHAVE = {"ollama"}


def exige_chave_de_api() -> bool:
    """Se o provider configurado precisa de uma chave para funcionar."""
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()
    return provider not in PROVIDERS_SEM_CHAVE


def configuracao_ausente() -> list[str]:
    """Variáveis que faltam ou estão inválidas para o LLM funcionar.

    Lista vazia significa configuração completa. É a fonte única: daqui a UI
    decide se avisa e desabilita o chat, e daqui `_construir_modelo` decide se
    pode construir o modelo. Duas listas separadas divergiriam.
    """
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()

    if provider not in DEFAULT_BASE_URLS:
        # Nada mais faz sentido checar: não sabemos o que esse provider exige.
        return ["LLM_PROVIDER"]

    faltando: list[str] = []

    # A chave não é exigida de todo provider: `ollama` roda local e dispensa.
    if not (settings.LLM_API_KEY or "").strip() and exige_chave_de_api():
        faltando.append("LLM_API_KEY")

    # `LLM_MODEL` não tem valor padrão de propósito. Chutar `gpt-4o-mini` daria
    # um erro 404 do provider em vez de uma mensagem dizendo o que configurar —
    # e o nome do modelo é específico do deployment de quem está rodando.
    if not (settings.LLM_MODEL or "").strip():
        faltando.append("LLM_MODEL")

    # Só o `custom` exige endpoint: os demais têm base URL conhecida, e para
    # eles uma `LLM_BASE_URL` vazia é o caso normal, não uma falta.
    if provider == "custom" and not (settings.LLM_BASE_URL or "").strip():
        faltando.append("LLM_BASE_URL")

    return faltando


class LLMConfigError(RuntimeError):
    """Configuração de provider LLM inválida ou incompleta."""


def _resolve_base_url(provider: str) -> str | None:
    """Base URL efetiva: a explícita vence a padrão do provider."""
    explicita = (settings.LLM_BASE_URL or "").strip()
    if explicita:
        return explicita

    base_url = DEFAULT_BASE_URLS[provider]
    if base_url is None and provider == "custom":
        raise LLMConfigError(
            "LLM_PROVIDER=custom exige LLM_BASE_URL preenchida com o "
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

    faltando = configuracao_ausente()
    if faltando:
        raise LLMConfigError(
            f"Configuração de LLM incompleta para LLM_PROVIDER='{provider}'. "
            f"Variáveis de ambiente ausentes: {', '.join(faltando)}. "
            f"Ver a seção Configuração do README."
        )

    api_key = (settings.LLM_API_KEY or "").strip()

    base_url = _resolve_base_url(provider)

    provider_kwargs: dict[str, str] = {
        # O SDK da OpenAI exige uma chave não vazia mesmo em endpoints locais.
        "api_key": api_key or "no-key-required",
    }
    if base_url:
        provider_kwargs["base_url"] = base_url

    logger.info(
        "event=llm_configurado provider=%s model=%s base_url=%s",
        provider,
        settings.LLM_MODEL,
        base_url,
    )
    return OpenAIChatModel(
        settings.LLM_MODEL,
        provider=OpenAIProvider(**provider_kwargs),
    )
