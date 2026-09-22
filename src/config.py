"""Configurações centralizadas da aplicação."""

import logging
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Carregar .env do diretório raiz do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _resolver_chave_do_cookie() -> tuple[str, bool]:
    """Chave de assinatura do cookie de sessão, gerando uma se não houver.

    Devolve `(chave, foi_gerada)`.

    O cookie de sessão é assinado com esta chave: quem a conhece consegue
    forjar um cookie e entrar como qualquer usuário sem passar pelo login. Um
    valor fixo no código seria público, então na ausência da variável é melhor
    sortear uma na inicialização.

    O preço é que a chave muda a cada boot do processo, invalidando as sessões
    abertas. Em produção, defina `AUTH_COOKIE_KEY` — sem ela, além do relogin a
    cada restart, réplicas diferentes assinariam com chaves diferentes e o
    usuário seria deslogado de forma aparentemente aleatória.
    """
    do_ambiente = (os.getenv("AUTH_COOKIE_KEY") or "").strip()
    if do_ambiente:
        return do_ambiente, False

    logger.warning(
        "event=auth_cookie_key_gerada "
        "detalhe=AUTH_COOKIE_KEY_ausente_chave_aleatoria_por_processo "
        "impacto=sessoes_caem_a_cada_restart_e_nao_funcionam_com_replicas "
        "acao=defina_AUTH_COOKIE_KEY_no_ambiente"
    )
    return secrets.token_urlsafe(48), True


class Settings:
    """Configurações da aplicação carregadas de variáveis de ambiente."""

    # LLM
    # Prefixo `LLM_` em tudo: a POC fala com todo provider pela API
    # OpenAI-compatible (ADR 0006), então a credencial é do provider escolhido
    # em LLM_PROVIDER, não da OpenAI.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    # Sem valor padrão de propósito: o nome do modelo é específico do
    # deployment de quem roda (no Azure é o nome do deployment, não o do
    # modelo). Um chute produziria um 404 do provider em vez de uma mensagem
    # dizendo o que falta configurar. Ver `provider.configuracao_ausente`.
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    # Modelo do agente de busca. Vazio usa o LLM_MODEL: a decisão de qual
    # imóvel mostrar é tão sensível quanto a de como falar dele. A variável
    # existe para poder trocar só a busca por um modelo mais rápido, já que ela
    # roda dentro do turno e a latência dela se soma à da resposta.
    LLM_MODEL_BUSCA: str = os.getenv("LLM_MODEL_BUSCA", "")

    # Banco de Dados
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://sdr:sdr_dev_pass@localhost:5432/agente_sdr",
    )
    # Credencial da role somente-leitura usada para executar o SQL que o agente
    # de busca escreve. É o único código do sistema que ninguém revisou antes
    # de rodar, e este banco guarda leads, telefones e conversas.
    DB_USER_BUSCA: str = "busca_ro"
    DB_PASSWORD_BUSCA: str = os.getenv("DB_PASSWORD_BUSCA", "busca_ro_dev_pass")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Autenticação
    AUTH_COOKIE_KEY, AUTH_COOKIE_KEY_GERADA = _resolver_chave_do_cookie()

    # Limites de custo LLM
    LLM_DAILY_TOKEN_BUDGET: int = int(os.getenv("LLM_DAILY_TOKEN_BUDGET", "1500000"))
    LLM_MONTHLY_TOKEN_BUDGET: int = int(os.getenv("LLM_MONTHLY_TOKEN_BUDGET", "10000000"))
    LLM_MAX_TURNS_PER_CONVERSATION: int = int(os.getenv("LLM_MAX_TURNS_PER_CONVERSATION", "30"))
    # Acompanha o teto de turnos: 30 turnos com busca frequente passam de 400
    # mil tokens, e um teto menor faria o handover disparar por causa da
    # busca, e nao por causa do tamanho da conversa.
    LLM_MAX_TOKENS_PER_CONVERSATION: int = int(os.getenv("LLM_MAX_TOKENS_PER_CONVERSATION", "400000"))

    # Observabilidade
    LOGFIRE_TOKEN: str = os.getenv("LOGFIRE_TOKEN", "")

    @property
    def database_url_safe(self) -> str:
        """URL do banco normalizada para o driver psycopg 3.

        O projeto depende de `psycopg[binary]` (psycopg 3). Sem o prefixo
        explícito, o SQLAlchemy assume `psycopg2`, que não é instalado.
        """
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def database_url_busca(self) -> str:
        """Mesma instância e mesmo banco, com a credencial somente-leitura.

        Derivada da `DATABASE_URL` em vez de configurada à parte: host, porta e
        nome do banco são os mesmos, e duas URLs completas dariam duas chances
        de apontar para lugares diferentes — inclusive na suíte de testes, que
        troca o nome do banco em tempo de execução.
        """
        partes = urlsplit(self.database_url_safe)
        porta = f":{partes.port}" if partes.port else ""
        credencial = f"{quote(self.DB_USER_BUSCA)}:{quote(self.DB_PASSWORD_BUSCA)}"
        return urlunsplit(
            partes._replace(netloc=f"{credencial}@{partes.hostname}{porta}")
        )


settings = Settings()
