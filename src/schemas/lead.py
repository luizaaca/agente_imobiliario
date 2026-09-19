"""Schemas Pydantic para Lead."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LeadStatus(str, Enum):
    """Status do lead no funil."""
    NOVO = "novo"
    EM_QUALIFICACAO = "em_qualificacao"
    QUALIFICADO = "qualificado"
    AGENDADO = "agendado"
    INATIVO = "inativo"


class LeadIntent(str, Enum):
    """Intenção declarada do lead."""
    COMPRA = "compra"
    ALUGUEL = "aluguel"
    INVESTIMENTO = "investimento"


class Urgencia(str, Enum):
    """Nível de urgência."""
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"


class LeadBase(BaseModel):
    """Campos base do lead."""
    nome: Optional[str] = Field(None, max_length=120)
    telefone: Optional[str] = Field(None, max_length=30)
    status: LeadStatus = LeadStatus.NOVO
    intencao: Optional[LeadIntent] = None
    tipologia_interesse: Optional[str] = Field(None, max_length=30)
    orcamento_min: Optional[Decimal] = Field(None, ge=0)
    orcamento_max: Optional[Decimal] = Field(None, ge=0)
    forma_pagamento: Optional[str] = Field(None, max_length=30)
    regiao_interesse: Optional[str] = Field(None, max_length=80)
    bairro_interesse: Optional[str] = Field(None, max_length=80)
    quartos: Optional[int] = Field(None, ge=0)
    urgencia: Optional[Urgencia] = None
    motivo_busca: Optional[str] = Field(None, max_length=120)
    perfil: Optional[str] = Field(None, max_length=30)
    canal_origem: Optional[str] = Field(None, max_length=30)
    amenidades_desejadas: Optional[str] = None
    score: Optional[Decimal] = Field(None, ge=0, le=10)
    perfil_narrativo: Optional[str] = None
    resumo: Optional[str] = None

    @field_validator("orcamento_max")
    @classmethod
    def orcamento_max_gte_min(cls, v, info):
        min_val = info.data.get("orcamento_min")
        if v is not None and min_val is not None and v < min_val:
            raise ValueError("orcamento_max deve ser >= orcamento_min")
        return v


class LeadCreate(LeadBase):
    """Schema para criação de lead."""
    pass


class LeadUpdate(BaseModel):
    """Schema para atualização parcial do lead."""
    nome: Optional[str] = None
    telefone: Optional[str] = None
    status: Optional[LeadStatus] = None
    intencao: Optional[LeadIntent] = None
    tipologia_interesse: Optional[str] = None
    orcamento_min: Optional[Decimal] = None
    orcamento_max: Optional[Decimal] = None
    forma_pagamento: Optional[str] = None
    regiao_interesse: Optional[str] = None
    bairro_interesse: Optional[str] = None
    quartos: Optional[int] = None
    urgencia: Optional[Urgencia] = None
    motivo_busca: Optional[str] = None
    perfil: Optional[str] = None
    canal_origem: Optional[str] = None
    amenidades_desejadas: Optional[str] = None
    score: Optional[Decimal] = None
    perfil_narrativo: Optional[str] = None
    resumo: Optional[str] = None


class LeadResponse(LeadBase):
    """Schema de resposta com dados completos do lead."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
