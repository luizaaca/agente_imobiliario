"""Serviço para agendamento de visitas e reuniões."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Agendamento, Lead

logger = logging.getLogger(__name__)


class SchedulingService:
    """Serviço de domínio para agendamentos."""

    def create(
        self,
        lead_id: int,
        tipo: str,
        data_hora: datetime,
        observacoes: Optional[str] = None,
        db: Session = None,
        imovel_id: Optional[int] = None,
    ) -> Agendamento:
        """Cria um novo agendamento e atualiza o status do lead."""
        if tipo not in ("visita", "reuniao"):
            raise ValueError(f"Tipo de agendamento inválido: {tipo}")

        agendamento = Agendamento(
            lead_id=lead_id,
            tipo=tipo,
            data_hora=data_hora,
            observacoes=observacoes,
            imovel_id=imovel_id,
            status="pendente",
        )
        db.add(agendamento)

        # Atualizar status do lead para 'agendado'
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead:
            lead.status = "agendado"

        db.commit()
        db.refresh(agendamento)
        logger.info(
            f"Agendamento criado: lead_id={lead_id}, tipo={tipo}, "
            f"data_hora={data_hora}, imovel_id={imovel_id}"
        )
        return agendamento

    def list_by_lead(
        self,
        lead_id: int,
        db: Session,
    ) -> list[Agendamento]:
        """Lista agendamentos de um lead ordenados por data."""
        return (
            db.query(Agendamento)
            .filter(Agendamento.lead_id == lead_id)
            .order_by(Agendamento.data_hora.desc())
            .all()
        )

    def update_status(
        self,
        agendamento_id: int,
        status: str,
        db: Session,
    ) -> Optional[Agendamento]:
        """Atualiza o status de um agendamento."""
        valid_statuses = ("pendente", "confirmado", "cancelado", "realizado")
        if status not in valid_statuses:
            raise ValueError(f"Status inválido: {status}. Válidos: {valid_statuses}")

        agendamento = db.query(Agendamento).filter(
            Agendamento.id == agendamento_id
        ).first()
        if agendamento:
            agendamento.status = status
            db.commit()
            db.refresh(agendamento)
            logger.info(
                f"Agendamento {agendamento_id} atualizado para status={status}"
            )
        return agendamento

    def get_pending_count(self, db: Session) -> int:
        """Retorna quantidade de agendamentos pendentes."""
        from sqlalchemy import func
        return (
            db.query(func.count(Agendamento.id))
            .filter(Agendamento.status == "pendente")
            .scalar() or 0
        )
