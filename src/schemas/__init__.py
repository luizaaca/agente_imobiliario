"""Exportação dos schemas."""

from .agendamento import (
    AgendamentoCreate,
    AgendamentoResponse,
    StatusAgendamento,
    TipoAgendamento,
)
from .agent import (
    AgendamentoInput,
    FollowUpInput,
    FollowUpOutput,
    PerfilLeadUpdate,
    QualificacaoInput,
    ResumoCorretorOutput,
)
from .imovel import (
    BuscaImovelParams,
    ImovelBase,
    ImovelBuscaResult,
    ImovelResponse,
)
from .lead import (
    LeadBase,
    LeadCreate,
    LeadIntent,
    LeadResponse,
    LeadStatus,
    LeadUpdate,
    Urgencia,
)
from .mensagem import (
    MensagemCreate,
    MensagemResponse,
    MessageRole,
    MessageStatus,
    MessageType,
)

__all__ = [
    # lead.py
    "LeadStatus",
    "LeadIntent",
    "Urgencia",
    "LeadBase",
    "LeadCreate",
    "LeadUpdate",
    "LeadResponse",
    # imovel.py
    "ImovelBase",
    "ImovelResponse",
    "BuscaImovelParams",
    "ImovelBuscaResult",
    # agendamento.py
    "TipoAgendamento",
    "StatusAgendamento",
    "AgendamentoCreate",
    "AgendamentoResponse",
    # mensagem.py
    "MessageRole",
    "MessageType",
    "MessageStatus",
    "MensagemCreate",
    "MensagemResponse",
    # agent.py
    "QualificacaoInput",
    "PerfilLeadUpdate",
    "AgendamentoInput",
    "ResumoCorretorOutput",
    "FollowUpInput",
    "FollowUpOutput",
]
