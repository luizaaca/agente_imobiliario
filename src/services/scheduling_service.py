"""Serviço para agendamento de visitas e reuniões."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Agendamento, Lead

logger = logging.getLogger(__name__)


class SchedulingService:
    """Serviço de domínio para agendamentos."""

    STATUS_VALIDOS = ("pendente", "confirmado", "cancelado", "realizado")
    TIPOS_VALIDOS = ("visita", "reuniao")

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
        if tipo not in self.TIPOS_VALIDOS:
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
            "event=agendamento_criado lead_id=%s agendamento_id=%s tipo=%s "
            "data_hora=%s imovel_id=%s status=ok",
            lead_id, agendamento.id, tipo, data_hora, imovel_id,
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

    def get(self, agendamento_id: int, db: Session) -> Optional[Agendamento]:
        """Busca um agendamento pelo ID."""
        return (
            db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
        )

    def editar(
        self,
        agendamento_id: int,
        db: Session,
        tipo: str,
        data_hora: datetime,
        status: str,
        observacoes: Optional[str] = None,
        imovel_id: Optional[int] = None,
    ) -> Optional[Agendamento]:
        """Reescreve um agendamento com o que o corretor deixou na ficha.

        Grava todos os campos, inclusive os vazios: aqui `None` significa "o
        corretor apagou", e não "não foi informado". É o mesmo critério da
        edição de lead — o caminho manual precisa conseguir limpar o que veio
        errado da conversa.

        O status do lead não é tocado: cancelar uma visita não devolve o lead
        para `qualificado` sozinho, porque só quem está atendendo sabe se a
        oportunidade morreu ou vai ser remarcada.
        """
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo de agendamento inválido: {tipo}")
        if status not in self.STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {status}")

        agendamento = self.get(agendamento_id, db)
        if not agendamento:
            return None

        agendamento.tipo = tipo
        agendamento.data_hora = data_hora
        agendamento.status = status
        agendamento.observacoes = observacoes
        agendamento.imovel_id = imovel_id

        db.commit()
        db.refresh(agendamento)
        logger.info(
            "event=agendamento_editado agendamento_id=%s lead_id=%s tipo=%s "
            "data_hora=%s status=%s imovel_id=%s",
            agendamento_id, agendamento.lead_id, tipo, data_hora, status,
            imovel_id,
        )
        return agendamento

    def excluir(self, agendamento_id: int, db: Session) -> bool:
        """Apaga o agendamento de vez.

        Diferente de marcar `cancelado`, que continua sendo o caminho quando a
        visita existiu e nao aconteceu: excluir e para o compromisso que nunca
        deveria ter sido criado — a data errada, o lead errado, o teste.

        O status do lead nao volta atras. Ele pode ter outros agendamentos, e
        decidir se a oportunidade regrediu no funil e de quem esta atendendo.
        """
        agendamento = self.get(agendamento_id, db)
        if not agendamento:
            return False

        lead_id = agendamento.lead_id
        db.delete(agendamento)
        db.commit()
        logger.info(
            "event=agendamento_excluido agendamento_id=%s lead_id=%s",
            agendamento_id, lead_id,
        )
        return True

    def update_status(
        self,
        agendamento_id: int,
        status: str,
        db: Session,
    ) -> Optional[Agendamento]:
        """Atualiza o status de um agendamento."""
        if status not in self.STATUS_VALIDOS:
            raise ValueError(
                f"Status inválido: {status}. Válidos: {self.STATUS_VALIDOS}"
            )

        agendamento = db.query(Agendamento).filter(
            Agendamento.id == agendamento_id
        ).first()
        if agendamento:
            agendamento.status = status
            db.commit()
            db.refresh(agendamento)
            logger.info(
                "event=agendamento_atualizado agendamento_id=%s lead_id=%s "
                "novo_status=%s",
                agendamento_id, agendamento.lead_id, status,
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
