"""Schemas Pydantic para Imóveis."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ImovelBase(BaseModel):
    """Campos base do imóvel."""
    titulo: str = Field(..., max_length=200)
    descricao: Optional[str] = None
    tipo: Optional[str] = Field(None, max_length=50)
    finalidade: Optional[str] = Field(None, max_length=50)
    preco: Decimal = Field(..., ge=0)
    condominio: Optional[Decimal] = Field(None, ge=0)
    iptu: Optional[Decimal] = Field(None, ge=0)
    area_util: Optional[Decimal] = Field(None, ge=0)
    area_total: Optional[Decimal] = Field(None, ge=0)
    quartos: Optional[int] = Field(None, ge=0)
    suites: Optional[int] = Field(None, ge=0)
    banheiros: Optional[int] = Field(None, ge=0)
    vagas: Optional[int] = Field(None, ge=0)
    cep: Optional[str] = Field(None, max_length=20)
    logradouro: Optional[str] = Field(None, max_length=150)
    numero: Optional[str] = Field(None, max_length=20)
    complemento: Optional[str] = Field(None, max_length=100)
    bairro: Optional[str] = Field(None, max_length=80)
    cidade: Optional[str] = Field(None, max_length=80)
    estado: Optional[str] = Field(None, max_length=2)
    regiao: Optional[str] = Field(None, max_length=80)
    amenidades: Optional[str] = None
    status: str = Field("ativo", max_length=30)
    url_fotos: Optional[str] = None


class ImovelResponse(ImovelBase):
    """Schema de resposta com dados completos do imóvel."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BuscaImovelParams(BaseModel):
    """Parâmetros de entrada para busca de imóveis."""
    intencao: Optional[str] = None
    orcamento_min: Optional[Decimal] = None
    orcamento_max: Optional[Decimal] = None
    regiao_interesse: Optional[str] = None
    bairro_interesse: Optional[str] = None
    quartos: Optional[int] = None
    termos_livres: Optional[str] = None
    limite_resultados: int = 5


class ImovelBuscaResult(ImovelBase):
    """Resultado da busca de imóvel incluindo justificativa."""
    id: int
    justificativa_aderencia: Optional[str] = None
