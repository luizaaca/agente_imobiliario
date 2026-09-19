"""Serviço de rastreamento e controle de custos de LLM."""

import logging
from datetime import datetime, timezone
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
    ) -> LLMUsage:
        """Registra uso de LLM no banco."""
        usage = LLMUsage(
            lead_id=lead_id,
            conversation_turn=turn,
            model=model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            tokens_total=tokens_in + tokens_out,
            estimated_cost_usd=self.estimate_cost(model, tokens_in, tokens_out),
            operation=operation,
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        logger.debug(
            f"LLM usage registrado: lead_id={lead_id}, model={model}, "
            f"tokens={tokens_in + tokens_out}, operation={operation}"
        )
        return usage

    def get_conversation_tokens(self, lead_id: int, db: Session) -> int:
        """Total de tokens consumidos por uma conversa."""
        return (
            db.query(func.sum(LLMUsage.tokens_total))
            .filter(LLMUsage.lead_id == lead_id)
            .scalar() or 0
        )

    def get_conversation_turns(self, lead_id: int, db: Session) -> int:
        """Total de turnos de chat de uma conversa."""
        return (
            db.query(func.count(LLMUsage.id))
            .filter(
                LLMUsage.lead_id == lead_id,
                LLMUsage.operation == "chat",
            )
            .scalar() or 0
        )

    def get_daily_tokens(self, db: Session) -> int:
        """Total de tokens consumidos hoje."""
        today = datetime.now(timezone.utc).date()
        return (
            db.query(func.sum(LLMUsage.tokens_total))
            .filter(func.date(LLMUsage.created_at) == today)
            .scalar() or 0
        )

    def get_monthly_tokens(self, db: Session) -> int:
        """Total de tokens consumidos no mês atual."""
        now = datetime.now(timezone.utc)
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
        today = datetime.now(timezone.utc).date()
        return (
            db.query(func.sum(LLMUsage.estimated_cost_usd))
            .filter(func.date(LLMUsage.created_at) == today)
            .scalar() or 0.0
        )

    def get_monthly_cost(self, db: Session) -> float:
        """Custo estimado total do mês em USD."""
        now = datetime.now(timezone.utc)
        return (
            db.query(func.sum(LLMUsage.estimated_cost_usd))
            .filter(
                func.extract("year", LLMUsage.created_at) == now.year,
                func.extract("month", LLMUsage.created_at) == now.month,
            )
            .scalar() or 0.0
        )

    def get_dashboard_summary(self, db: Session) -> dict:
        """Dados consolidados para exibição no dashboard."""
        return {
            "daily_tokens": self.get_daily_tokens(db),
            "daily_budget": settings.LLM_DAILY_TOKEN_BUDGET,
            "monthly_tokens": self.get_monthly_tokens(db),
            "monthly_budget": settings.LLM_MONTHLY_TOKEN_BUDGET,
            "daily_cost_usd": self.get_daily_cost(db),
            "monthly_cost_usd": self.get_monthly_cost(db),
        }
