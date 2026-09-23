"""Schemas Pydantic para Agendamento.

Os campos espelham `src.db.models.Agendamento` (ver `tests/test_schemas.py`).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class TipoAgendamento(str, Enum):
    """Tipo do agendamento."""
    VISITA = "visita"
    REUNIAO = "reuniao"


class StatusAgendamento(str, Enum):
    """Status do agendamento."""
    PENDENTE = "pendente"
    CONFIRMADO = "confirmado"
    CANCELADO = "cancelado"
    REALIZADO = "realizado"


class AgendamentoCreate(BaseModel):
    """Schema para criação de agendamento."""
    lead_id: int
    tipo: TipoAgendamento
    data_hora: datetime
    observacoes: Optional[str] = None


class AgendamentoResponse(AgendamentoCreate):
    """Schema de resposta de agendamento."""
    id: int
    status: StatusAgendamento
    created_at: datetime

    model_config = {"from_attributes": True}
