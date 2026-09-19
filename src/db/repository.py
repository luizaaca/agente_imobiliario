"""Repositório de acesso a dados com operações CRUD genéricas."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select, update, func, or_
from sqlalchemy.orm import Session

from src.db.models import (
    Lead, Mensagem, Agendamento, Imovel, LLMUsage, LeadChannelIdentity, FollowUpAttempt
)

class Repository:
    """Classe base do repositório para acesso aos dados."""

    def __init__(self, db: Session):
        self.db = db

    # --- Leads ---
    def create_lead(self, lead_data: Dict[str, Any]) -> Lead:
        lead = Lead(**lead_data)
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def get_lead_by_id(self, lead_id: int) -> Optional[Lead]:
        return self.db.query(Lead).filter(Lead.id == lead_id).first()

    def update_lead(self, lead_id: int, updates: Dict[str, Any]) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if lead:
            for key, value in updates.items():
                setattr(lead, key, value)
            self.db.commit()
            self.db.refresh(lead)
        return lead

    def list_leads(self, **filters) -> List[Lead]:
        query = self.db.query(Lead)
        for key, value in filters.items():
            query = query.filter(getattr(Lead, key) == value)
        return query.all()

    # --- LeadChannelIdentities ---
    def get_lead_by_channel_identity(self, channel: str, external_chat_id: str) -> Optional[Lead]:
        identity = (
            self.db.query(LeadChannelIdentity)
            .filter_by(channel=channel, external_chat_id=external_chat_id)
            .first()
        )
        return identity.lead if identity else None

    def get_or_create_channel_identity(self, lead_id: int, channel: str, external_chat_id: str) -> LeadChannelIdentity:
        identity = (
            self.db.query(LeadChannelIdentity)
            .filter_by(lead_id=lead_id, channel=channel, external_chat_id=external_chat_id)
            .first()
        )
        if not identity:
            identity = LeadChannelIdentity(
                lead_id=lead_id,
                channel=channel,
                external_chat_id=external_chat_id,
                is_primary=True
            )
            self.db.add(identity)
            self.db.commit()
            self.db.refresh(identity)
        else:
            identity.last_seen_at = func.now()
            self.db.commit()
        return identity

    # --- Mensagens ---
    def create_mensagem(self, msg_data: Dict[str, Any]) -> Mensagem:
        msg = Mensagem(**msg_data)
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def list_mensagens_by_lead(self, lead_id: int) -> List[Mensagem]:
        return (
            self.db.query(Mensagem)
            .filter(Mensagem.lead_id == lead_id)
            .order_by(Mensagem.timestamp.asc())
            .all()
        )

    # --- Imoveis ---
    def search_imoveis(self, filters: Dict[str, Any], query_text: Optional[str] = None) -> List[Imovel]:
        """Busca estruturada de imóveis. TODO: Melhorar a busca textual no futuro."""
        query = self.db.query(Imovel).filter(Imovel.disponivel == True)

        for key, value in filters.items():
            if hasattr(Imovel, key) and value is not None:
                if key in ['preco', 'area_m2'] and isinstance(value, tuple):
                    min_val, max_val = value
                    query = query.filter(getattr(Imovel, key) >= min_val, getattr(Imovel, key) <= max_val)
                else:
                    query = query.filter(getattr(Imovel, key) == value)
        
        if query_text:
            search_filter = or_(
                Imovel.titulo.ilike(f"%{query_text}%"),
                Imovel.descricao.ilike(f"%{query_text}%"),
                Imovel.tags.ilike(f"%{query_text}%")
            )
            query = query.filter(search_filter)

        return query.limit(20).all()

    # --- Agendamentos ---
    def create_agendamento(self, agendamento_data: Dict[str, Any]) -> Agendamento:
        agendamento = Agendamento(**agendamento_data)
        self.db.add(agendamento)
        self.db.commit()
        self.db.refresh(agendamento)
        return agendamento

    def list_agendamentos_by_lead(self, lead_id: int) -> List[Agendamento]:
        return self.db.query(Agendamento).filter(Agendamento.lead_id == lead_id).all()

    def update_agendamento_status(self, agendamento_id: int, status: str) -> Optional[Agendamento]:
        agendamento = self.db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
        if agendamento:
            agendamento.status = status
            self.db.commit()
            self.db.refresh(agendamento)
        return agendamento

    # --- LLMUsage ---
    def record_llm_usage(self, usage_data: Dict[str, Any]) -> LLMUsage:
        usage = LLMUsage(**usage_data)
        self.db.add(usage)
        self.db.commit()
        self.db.refresh(usage)
        return usage

    # --- FollowUpAttempts ---
    def record_followup_attempt(self, followup_data: Dict[str, Any]) -> FollowUpAttempt:
        followup = FollowUpAttempt(**followup_data)
        self.db.add(followup)
        self.db.commit()
        self.db.refresh(followup)
        return followup
