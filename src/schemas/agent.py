"""Schemas Pydantic para tools e interações do Agente."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from .lead import LeadIntent, Urgencia


class QualificacaoInput(BaseModel):
    """Dados estruturados para registrar a qualificação de um lead."""
    intencao: Optional[LeadIntent] = None
    tipologia_interesse: Optional[str] = None
    orcamento_min: Optional[Decimal] = None
    orcamento_max: Optional[Decimal] = None
    regiao_interesse: Optional[str] = None
    bairro_interesse: Optional[str] = None
    quartos: Optional[int] = None
    urgencia: Optional[Urgencia] = None
    motivo_busca: Optional[str] = None


class PerfilLeadUpdate(BaseModel):
    """Dados para atualização do perfil do lead."""
    perfil: Optional[str] = None
    amenidades_desejadas: Optional[str] = None
    perfil_narrativo: Optional[str] = None
    resumo: Optional[str] = None


class AgendamentoInput(BaseModel):
    """Dados de entrada para a tool de agendar_reuniao."""
    tipo: str = Field(description="Deve ser 'visita' ou 'reuniao'")
    data_hora: datetime
    observacoes: Optional[str] = None
    remarcar: bool = False


class ResumoCorretorOutput(BaseModel):
    """Output estruturado para o resumo gerado para o corretor."""
    lead_id: int
    nome_lead: str
    status_lead: str
    intencao: str
    resumo_interacao: str
    pontos_atencao: list[str]
    recomendacao_proximo_passo: str


class FollowUpInput(BaseModel):
    """Entrada interna para gerar um follow-up."""
    lead_id: int
    contexto: Optional[str] = None
    dias_inatividade: int


class FollowUpOutput(BaseModel):
    """Saída da geração de follow-up."""
    mensagem: str
    regua: str = Field(description="A régua/estágio do follow-up")
    envio_recomendado: datetime
