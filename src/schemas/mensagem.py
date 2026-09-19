"""Schemas Pydantic para Mensagens."""

from datetime import datetime
from enum import Enum
from typing import Optional

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
    channel: str = Field(..., max_length=50)
    role: MessageRole
    message_type: MessageType
    content: str
    tool_calls: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    status: MessageStatus = MessageStatus.CREATED


class MensagemResponse(MensagemCreate):
    """Schema de resposta de mensagem."""
    id: int
    timestamp: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
