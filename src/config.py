"""Configurações centralizadas da aplicação."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Carregar .env do diretório raiz do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Configurações da aplicação carregadas de variáveis de ambiente."""

    # LLM
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")

    # Banco de Dados
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://sdr:sdr_dev_pass@localhost:5432/agente_sdr",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Autenticação
    AUTH_COOKIE_KEY: str = os.getenv("AUTH_COOKIE_KEY", "dev_fallback_key")

    # Limites de custo LLM
    LLM_DAILY_TOKEN_BUDGET: int = int(os.getenv("LLM_DAILY_TOKEN_BUDGET", "100000"))
    LLM_MONTHLY_TOKEN_BUDGET: int = int(os.getenv("LLM_MONTHLY_TOKEN_BUDGET", "3000000"))
    LLM_MAX_TURNS_PER_CONVERSATION: int = int(os.getenv("LLM_MAX_TURNS_PER_CONVERSATION", "30"))
    LLM_MAX_TOKENS_PER_CONVERSATION: int = int(os.getenv("LLM_MAX_TOKENS_PER_CONVERSATION", "50000"))

    # Observabilidade
    LOGFIRE_TOKEN: str = os.getenv("LOGFIRE_TOKEN", "")

    @property
    def database_url_safe(self) -> str:
        """URL do banco com ajuste de compatibilidade."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


settings = Settings()
