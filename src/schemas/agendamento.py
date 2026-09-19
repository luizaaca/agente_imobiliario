"""Schemas Pydantic para Agendamento."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    imovel_id: Optional[int] = None


class AgendamentoResponse(AgendamentoCreate):
    """Schema de resposta de agendamento."""
    id: int
    status: StatusAgendamento
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
