"""Schemas Pydantic para Imóveis.

Os campos espelham `src.db.models.Imovel`. `tests/test_schemas.py` valida esse
espelhamento contra o ORM a cada execução da suíte, para que uma migration
futura não deixe este contrato para trás de novo.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ImovelBase(BaseModel):
    """Campos base do imóvel."""
    titulo: str = Field(..., max_length=200)
    tipo: str = Field(..., max_length=30)
    finalidade: str = Field(..., max_length=20)
    operacao: str = Field(..., max_length=20)
    bairro: str = Field(..., max_length=100)
    zona: Optional[str] = Field(None, max_length=50)
    cidade: str = Field("São Paulo", max_length=100)
    estado: str = Field("SP", max_length=2)
    preco: Decimal = Field(..., gt=0)
    quartos: int = Field(..., ge=0)
    suites: Optional[int] = Field(None, ge=0)
    banheiros: Optional[int] = Field(None, ge=0)
    vaga_garagem: Optional[int] = Field(None, ge=0)
    area_m2: Decimal = Field(..., gt=0)
    condominio: Optional[Decimal] = Field(None, ge=0)
    iptu_anual: Optional[Decimal] = Field(None, ge=0)
    descricao: Optional[str] = None
    tags: Optional[str] = None
    perfil_indicado: Optional[str] = Field(None, max_length=30)
    disponivel: bool = True
    imagem_url: Optional[str] = Field(None, max_length=500)


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

    model_config = {"from_attributes": True}
