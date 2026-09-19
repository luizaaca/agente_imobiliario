"""Schemas Pydantic para Mensagens.

Os campos espelham `src.db.models.Mensagem` (ver `tests/test_schemas.py`).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Papel do emissor da mensagem."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageType(str, Enum):
    """Tipo da mensagem."""
    CHAT = "chat"
    FOLLOWUP = "followup"
    SYSTEM_NOTICE = "system_notice"
    HANDOVER = "handover"


class MessageStatus(str, Enum):
    """Status da mensagem."""
    CREATED = "created"
    RECEIVED = "received"
    GENERATED = "generated"
    SENT = "sent"
    FAILED = "failed"


class MensagemCreate(BaseModel):
    """Schema para criação de mensagem."""
    lead_id: int
    channel: str = Field(..., max_length=30)
    role: MessageRole
    message_type: MessageType
    content: str
    status: MessageStatus = MessageStatus.CREATED
    channel_identity_id: Optional[int] = None
    external_message_id: Optional[str] = Field(None, max_length=100)
    in_reply_to_message_id: Optional[int] = None
    metadata_json: Optional[dict[str, Any]] = None


class MensagemResponse(MensagemCreate):
    """Schema de resposta de mensagem."""
    id: int
    timestamp: datetime
    sent_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
