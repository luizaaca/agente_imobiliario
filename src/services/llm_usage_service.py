"""Serviço de rastreamento e controle de custos de LLM."""

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import LLMUsage

logger = logging.getLogger(__name__)

# Tabela de preços por modelo (USD por 1M tokens)
PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
}


class LLMUsageService:
    """Serviço de governança de custos de LLM."""

    # Preço genérico para modelos fora da tabela; o número é um palpite, então
    # o uso é registrado em log para o custo não parecer mais preciso do que é.
    FALLBACK_PRICING = {"input": 1.0, "output": 3.0}

    def estimate_cost(
        self, model: str, tokens_in: int, tokens_out: int
    ) -> float:
        """Calcula custo estimado em USD."""
        prices = PRICING.get(model)
        if prices is None:
            prices = self.FALLBACK_PRICING
            logger.warning(
                "event=preco_desconhecido model=%s detalhe=usando_fallback "
                "usd_por_1M_in=%s usd_por_1M_out=%s",
                model, prices["input"], prices["output"],
            )
        cost = (
            (tokens_in / 1_000_000) * prices["input"]
            + (tokens_out / 1_000_000) * prices["output"]
        )
        return round(cost, 6)

    def record(
        self,
        lead_id: Optional[int],
        model: str,
        tokens_in: int,
        tokens_out: int,
        operation: str,
        db: Session,
        turn: Optional[int] = None,
        latency_ms: Optional[int] = None,
    ) -> LLMUsage:
        """Registra uma chamada bem-sucedida ao provider."""
        usage = LLMUsage(
            lead_id=lead_id,
            conversation_turn=turn,
            model=model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            tokens_total=tokens_in + tokens_out,
            estimated_cost_usd=self.estimate_cost(model, tokens_in, tokens_out),
            operation=operation,
            status="ok",
            latency_ms=latency_ms,
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        logger.info(
            "event=llm_usage_registrado lead_id=%s model=%s operation=%s "
            "tokens=%s latency_ms=%s status=ok",
            lead_id, model, operation, tokens_in + tokens_out, latency_ms,
        )
        return usage

    def record_failure(
        self,
        lead_id: Optional[int],
        model: str,
        operation: str,
        error_type: str,
        db: Session,
        latency_ms: Optional[int] = None,
    ) -> LLMUsage:
        """Registra uma chamada que falhou.

        Sem token e sem custo — a chamada nao chegou a produzir resposta — mas
        com linha no banco, porque uma falha que so existe no log nao entra na
        taxa de erro do dashboard.
        """
        usage = LLMUsage(
            lead_id=lead_id,
            model=model,
            tokens_input=0,
            tokens_output=0,
            tokens_total=0,
            estimated_cost_usd=0,
            operation=operation,
            status="erro",
            error_type=error_type,
            latency_ms=latency_ms,
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        logger.warning(
            "event=llm_usage_registrado lead_id=%s model=%s operation=%s "
            "latency_ms=%s status=erro error_type=%s",
            lead_id, model, operation, latency_ms, error_type,
        )
        return usage

    def get_conversation_tokens(self, lead_id: int, db: Session) -> int:
        """Total de tokens consumidos por uma conversa."""
        return (
            db.query(func.sum(LLMUsage.tokens_total))
            .filter(LLMUsage.lead_id == lead_id)
            .scalar() or 0
        )

    def get_conversation_cost(self, lead_id: int, db: Session) -> float:
        """Custo estimado de uma conversa inteira, em USD.

        Soma tudo que o lead consumiu: os turnos de chat, as idas do agente de
        busca ao catálogo e a consolidação do perfil. Quem olha uma conversa
        quer saber o que ela custou, e não o que cada agente custou dentro
        dela.
        """
        return float(
            db.query(func.sum(LLMUsage.estimated_cost_usd))
            .filter(LLMUsage.lead_id == lead_id)
            .scalar() or 0.0
        )

    def get_conversation_turns(self, lead_id: int, db: Session) -> int:
        """Total de turnos de chat de uma conversa.

        Só as chamadas que deram certo: uma falha do provider não gastou turno
        do lead, e contá-la anteciparia o handover por limite de conversa.
        """
        return (
            db.query(func.count(LLMUsage.id))
            .filter(
                LLMUsage.lead_id == lead_id,
                LLMUsage.operation == "chat",
                LLMUsage.status == "ok",
            )
            .scalar() or 0
        )

    def get_daily_tokens(self, db: Session) -> int:
        """Total de tokens consumidos hoje."""
        today = datetime.now(UTC).date()
        return (
            db.query(func.sum(LLMUsage.tokens_total))
            .filter(func.date(LLMUsage.created_at) == today)
            .scalar() or 0
        )

    def get_monthly_tokens(self, db: Session) -> int:
        """Total de tokens consumidos no mês atual."""
        now = datetime.now(UTC)
        return (
            db.query(func.sum(LLMUsage.tokens_total))
            .filter(
                func.extract("year", LLMUsage.created_at) == now.year,
                func.extract("month", LLMUsage.created_at) == now.month,
            )
            .scalar() or 0
        )

    def is_conversation_over_limit(
        self, lead_id: int, db: Session
    ) -> bool:
        """Verifica se a conversa excedeu os limites."""
        tokens = self.get_conversation_tokens(lead_id, db)
        turns = self.get_conversation_turns(lead_id, db)
        return (
            tokens >= settings.LLM_MAX_TOKENS_PER_CONVERSATION
            or turns >= settings.LLM_MAX_TURNS_PER_CONVERSATION
        )

    def is_daily_budget_exceeded(self, db: Session) -> bool:
        """Verifica se o budget diário foi excedido."""
        return self.get_daily_tokens(db) >= settings.LLM_DAILY_TOKEN_BUDGET

    def is_monthly_budget_exceeded(self, db: Session) -> bool:
        """Verifica se o budget mensal foi excedido."""
        return self.get_monthly_tokens(db) >= settings.LLM_MONTHLY_TOKEN_BUDGET

    def get_daily_cost(self, db: Session) -> float:
        """Custo estimado total do dia em USD."""
        today = datetime.now(UTC).date()
        return (
            db.query(func.sum(LLMUsage.estimated_cost_usd))
            .filter(func.date(LLMUsage.created_at) == today)
            .scalar() or 0.0
        )

    def get_monthly_cost(self, db: Session) -> float:
        """Custo estimado total do mês em USD."""
        now = datetime.now(UTC)
        return (
            db.query(func.sum(LLMUsage.estimated_cost_usd))
            .filter(
                func.extract("year", LLMUsage.created_at) == now.year,
                func.extract("month", LLMUsage.created_at) == now.month,
            )
            .scalar() or 0.0
        )

    def _do_dia(self, query):
        """Restringe uma query ao dia corrente."""
        return query.filter(func.date(LLMUsage.created_at) == datetime.now(UTC).date())

    def get_daily_latency_ms(self, db: Session) -> Optional[int]:
        """Tempo médio de resposta do provider hoje, em milissegundos.

        Só as chamadas bem-sucedidas: a latência de uma falha mede o timeout,
        não o tempo de resposta. `None` quando ainda não houve chamada — o
        dashboard mostra isso como "—" em vez de fingir um zero.
        """
        media = self._do_dia(
            db.query(func.avg(LLMUsage.latency_ms)).filter(
                LLMUsage.status == "ok", LLMUsage.latency_ms.isnot(None)
            )
        ).scalar()
        return int(media) if media is not None else None

    def get_daily_error_rate(self, db: Session) -> Optional[float]:
        """Fração das chamadas de hoje que falharam, de 0 a 1.

        `None` quando não houve chamada nenhuma: sem denominador, 0% diria que
        está tudo bem quando na verdade nada foi exercitado.
        """
        total = self._do_dia(db.query(func.count(LLMUsage.id))).scalar() or 0
        if not total:
            return None
        erros = self._do_dia(
            db.query(func.count(LLMUsage.id)).filter(LLMUsage.status == "erro")
        ).scalar() or 0
        return erros / total

    def get_dashboard_summary(self, db: Session) -> dict:
        """Dados consolidados para exibição no dashboard."""
        return {
            "daily_tokens": self.get_daily_tokens(db),
            "daily_budget": settings.LLM_DAILY_TOKEN_BUDGET,
            "monthly_tokens": self.get_monthly_tokens(db),
            "monthly_budget": settings.LLM_MONTHLY_TOKEN_BUDGET,
            "daily_cost_usd": self.get_daily_cost(db),
            "monthly_cost_usd": self.get_monthly_cost(db),
            "daily_latency_ms": self.get_daily_latency_ms(db),
            "daily_error_rate": self.get_daily_error_rate(db),
            "daily_budget_exceeded": self.is_daily_budget_exceeded(db),
            "monthly_budget_exceeded": self.is_monthly_budget_exceeded(db),
        }
