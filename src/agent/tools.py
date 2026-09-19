"""Tools tipadas do agente SDR imobiliário."""

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# --- Tool Input/Output Schemas ---

class BuscarImoveisInput(BaseModel):
    """Parâmetros para busca de imóveis no catálogo."""
    intencao: Optional[str] = Field(None, description="Intenção: compra ou aluguel")
    orcamento_min: Optional[float] = Field(None, description="Orçamento mínimo em R$")
    orcamento_max: Optional[float] = Field(None, description="Orçamento máximo em R$")
    regiao_interesse: Optional[str] = Field(None, description="Região ou zona de interesse")
    bairro_interesse: Optional[str] = Field(None, description="Bairro de interesse")
    quartos: Optional[int] = Field(None, description="Quantidade mínima de quartos")
    termos_livres: Optional[str] = Field(None, description="Termos de busca livre")
    limite_resultados: int = Field(5, description="Máximo de resultados")


class RegistrarQualificacaoInput(BaseModel):
    """Dados estruturados de qualificação do lead."""
    intencao: Optional[str] = None
    perfil: Optional[str] = None
    orcamento_min: Optional[float] = None
    orcamento_max: Optional[float] = None
    bairro_interesse: Optional[str] = None
    regiao_interesse: Optional[str] = None
    quartos: Optional[int] = None
    urgencia: Optional[str] = None
    motivo_busca: Optional[str] = None
    forma_pagamento: Optional[str] = None
    amenidades_desejadas: Optional[str] = None
    tipologia_interesse: Optional[str] = None


class AtualizarPerfilInput(BaseModel):
    """Input para atualizar o perfil narrativo do lead."""
    perfil_narrativo_atualizado: str = Field(..., description="Texto completo atualizado do perfil narrativo")
    motivo_atualizacao: Optional[str] = Field(None, description="Motivo da atualização")


class AgendarReuniaoInput(BaseModel):
    """Input para agendar visita ou reunião."""
    tipo: str = Field(..., description="Tipo: 'visita' ou 'reuniao'")
    data_hora: str = Field(..., description="Data e hora no formato YYYY-MM-DD HH:MM")
    observacoes: Optional[str] = Field(None, description="Observações para o corretor")
    imovel_id: Optional[int] = Field(None, description="ID do imóvel quando aplicável")


class GerarResumoInput(BaseModel):
    """Input para gerar resumo do corretor."""
    pass  # Uses lead_id from context
