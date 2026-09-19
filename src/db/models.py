"""Modelos ORM SQLAlchemy do banco de dados."""

from datetime import datetime
from typing import Optional, List, Any

from sqlalchemy import (
    BigInteger, String, Text, Numeric, SmallInteger, Boolean,
    CheckConstraint, func, ForeignKey, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TIMESTAMP


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nome: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    intencao: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    tipologia_interesse: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    orcamento_min: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    orcamento_max: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    forma_pagamento: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    regiao_interesse: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    bairro_interesse: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    quartos: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    urgencia: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    motivo_busca: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    perfil: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    canal_origem: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    amenidades_desejadas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    perfil_narrativo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resumo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    mensagens: Mapped[List["Mensagem"]] = relationship(back_populates="lead")
    agendamentos: Mapped[List["Agendamento"]] = relationship(back_populates="lead")
    llm_usages: Mapped[List["LLMUsage"]] = relationship(back_populates="lead")
    channel_identities: Mapped[List["LeadChannelIdentity"]] = relationship(back_populates="lead")
    followup_attempts: Mapped[List["FollowUpAttempt"]] = relationship(back_populates="lead")

    __table_args__ = (
        CheckConstraint("status IN ('novo','em_qualificacao','qualificado','agendado','inativo')", name="check_status"),
        CheckConstraint("intencao IN ('compra','aluguel','investimento')", name="check_intencao"),
        CheckConstraint("orcamento_min >= 0", name="check_orcamento_min"),
        CheckConstraint("orcamento_max >= 0", name="check_orcamento_max"),
        CheckConstraint("quartos >= 0", name="check_quartos"),
        CheckConstraint("urgencia IN ('baixa','media','alta')", name="check_urgencia"),
        CheckConstraint("score >= 0 AND score <= 10", name="check_score"),
    )

    def __repr__(self) -> str:
        return f"<Lead id={self.id} nome='{self.nome}'>"


class Mensagem(Base):
    __tablename__ = "mensagens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    channel_identity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    external_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    in_reply_to_message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mensagens.id"), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="mensagens")
    replies: Mapped[List["Mensagem"]] = relationship("Mensagem", remote_side=[id])

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system','tool')", name="check_role"),
        CheckConstraint("message_type IN ('chat','followup','system_notice','handover')", name="check_message_type"),
        CheckConstraint("status IN ('created','received','generated','sent','failed')", name="check_msg_status"),
    )

    def __repr__(self) -> str:
        return f"<Mensagem id={self.id} role='{self.role}'>"


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    data_hora: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    observacoes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="agendamentos")

    __table_args__ = (
        CheckConstraint("tipo IN ('visita','reuniao')", name="check_tipo_agendamento"),
        CheckConstraint("status IN ('pendente','confirmado','cancelado','realizado')", name="check_status_agendamento"),
    )

    def __repr__(self) -> str:
        return f"<Agendamento id={self.id} tipo='{self.tipo}' status='{self.status}'>"


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    finalidade: Mapped[str] = mapped_column(String(20), nullable=False)
    operacao: Mapped[str] = mapped_column(String(20), nullable=False)
    bairro: Mapped[str] = mapped_column(String(100), nullable=False)
    zona: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cidade: Mapped[str] = mapped_column(String(100), nullable=False, default="São Paulo")
    estado: Mapped[str] = mapped_column(String(2), nullable=False, default="SP")
    preco: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quartos: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    suites: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    banheiros: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    vaga_garagem: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    area_m2: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    condominio: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    iptu_anual: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    perfil_indicado: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    disponivel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    imagem_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    search_vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("tipo IN ('apartamento','casa','cobertura','terreno','comercial')", name="check_tipo_imovel"),
        CheckConstraint("finalidade IN ('residencial','comercial')", name="check_finalidade"),
        CheckConstraint("operacao IN ('venda','aluguel')", name="check_operacao"),
        CheckConstraint("preco > 0", name="check_preco"),
        CheckConstraint("quartos >= 0", name="check_imovel_quartos"),
        CheckConstraint("suites >= 0", name="check_suites"),
        CheckConstraint("banheiros >= 0", name="check_banheiros"),
        CheckConstraint("vaga_garagem >= 0", name="check_vagas"),
        CheckConstraint("area_m2 > 0", name="check_area"),
        CheckConstraint("condominio >= 0", name="check_condominio"),
        CheckConstraint("iptu_anual >= 0", name="check_iptu"),
    )

    def __repr__(self) -> str:
        return f"<Imovel id={self.id} titulo='{self.titulo}'>"


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)
    conversation_turn: Mapped[Optional[int]] = mapped_column(nullable=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    tokens_input: Mapped[int] = mapped_column(nullable=False)
    tokens_output: Mapped[int] = mapped_column(nullable=False)
    tokens_total: Mapped[int] = mapped_column(nullable=False)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="llm_usages")

    __table_args__ = (
        CheckConstraint("tokens_input >= 0", name="check_tokens_input"),
        CheckConstraint("tokens_output >= 0", name="check_tokens_output"),
        CheckConstraint("tokens_total >= 0", name="check_tokens_total"),
    )

    def __repr__(self) -> str:
        return f"<LLMUsage id={self.id} model='{self.model}'>"


class LeadChannelIdentity(Base):
    __tablename__ = "lead_channel_identities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_chat_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="channel_identities")

    def __repr__(self) -> str:
        return f"<LeadChannelIdentity id={self.id} channel='{self.channel}'>"


class FollowUpAttempt(Base):
    __tablename__ = "followup_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mensagens.id"), nullable=True)
    regua: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="followup_attempts")
    mensagem: Mapped[Optional["Mensagem"]] = relationship()

    __table_args__ = (
        CheckConstraint("regua IN ('lead_novo_sem_resposta','qualificacao_interrompida','pos_envio_imoveis','pos_agendamento')", name="check_regua"),
        CheckConstraint("attempt_number >= 1", name="check_attempt_number"),
        CheckConstraint("status IN ('generated','sent','failed','skipped')", name="check_followup_status"),
    )

    def __repr__(self) -> str:
        return f"<FollowUpAttempt id={self.id} regua='{self.regua}' attempt={self.attempt_number}>"
