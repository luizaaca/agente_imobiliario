"""Serviço para agendamento de visitas e reuniões."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Agendamento, Lead
from src.schemas.lead import LeadStatus
from src.services.lead_service import LeadService

logger = logging.getLogger(__name__)


class SchedulingService:
    """Serviço de domínio para agendamentos."""

    STATUS_VALIDOS = ("pendente", "confirmado", "cancelado", "realizado")
    TIPOS_VALIDOS = ("visita", "reuniao")
    # Compromissos que ainda estao de pe. `realizado` sai da lista junto com
    # `cancelado`: a visita ja aconteceu, e o lead nao esta mais esperando por
    # ela.
    STATUS_ATIVOS = ("pendente", "confirmado")

    def tem_compromisso_ativo(self, lead_id: int, db: Session) -> bool:
        """Se existe visita ou reuniao de pe para este lead."""
        return (
            db.query(Agendamento.id)
            .filter(
                Agendamento.lead_id == lead_id,
                Agendamento.status.in_(self.STATUS_ATIVOS),
            )
            .first()
            is not None
        )

    def sincronizar_status_do_lead(self, lead_id: int, db: Session) -> Optional[str]:
        """Faz o status do lead concordar com os compromissos dele.

        `agendado` nao e opiniao, e fato verificavel: ou existe visita marcada,
        ou nao existe. Por isso a sincronizacao vale nos dois sentidos —
        aparecendo compromisso o lead vai para `agendado`, sumindo o ultimo ele
        volta para onde os dados o colocam.

        Os outros estagios sao julgamento de quem atende e nao sao tocados
        aqui; `inativo` tambem fica de fora, porque um lead que parou de
        responder continua parado mesmo com uma visita antiga no calendario.

        Devolve o novo status quando houve mudanca, e `None` quando ja estava
        certo — e o que permite a quem chama saber se precisa avisar na tela.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead is None or lead.status == LeadStatus.INATIVO.value:
            return None

        tem = self.tem_compromisso_ativo(lead_id, db)
        esta_agendado = lead.status == LeadStatus.AGENDADO.value
        if tem == esta_agendado:
            return None

        lead.status = (
            LeadStatus.AGENDADO.value
            if tem
            else LeadService().status_sem_compromisso(lead)
        )
        db.commit()
        logger.info(
            "event=status_sincronizado_com_agenda lead_id=%s novo_status=%s "
            "tem_compromisso=%s",
            lead_id, lead.status, tem,
        )
        return lead.status

    def create(
        self,
        lead_id: int,
        tipo: str,
        data_hora: datetime,
        observacoes: Optional[str] = None,
        db: Session = None,
        imovel_id: Optional[int] = None,
    ) -> Agendamento:
        """Cria um agendamento, ou devolve o que ja existe igual a este.

        Idempotente de proposito. Sem isso, pedir duas vezes o mesmo
        compromisso — o que o agente faz quando nao tem a ferramenta certa a
        mao, e o que um duplo clique faz na tela — cria duas linhas para a
        mesma visita, e o painel passa a contar dois compromissos onde ha um.

        "Igual" e mesmo lead, mesma data e hora, mesmo imovel e ainda de pe.
        Um compromisso cancelado nao impede remarcar para o mesmo horario.
        """
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo de agendamento inválido: {tipo}")

        ja_existe = (
            db.query(Agendamento)
            .filter(
                Agendamento.lead_id == lead_id,
                Agendamento.data_hora == data_hora,
                Agendamento.imovel_id == imovel_id,
                Agendamento.status.in_(self.STATUS_ATIVOS),
            )
            .first()
        )
        if ja_existe is not None:
            logger.info(
                "event=agendamento_ja_existia lead_id=%s agendamento_id=%s "
                "data_hora=%s imovel_id=%s acao=reaproveitado",
                lead_id, ja_existe.id, data_hora, imovel_id,
            )
            return ja_existe

        agendamento = Agendamento(
            lead_id=lead_id,
            tipo=tipo,
            data_hora=data_hora,
            observacoes=observacoes,
            imovel_id=imovel_id,
            status="pendente",
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        logger.info(
            "event=agendamento_criado lead_id=%s agendamento_id=%s tipo=%s "
            "data_hora=%s imovel_id=%s status=ok",
            lead_id, agendamento.id, tipo, data_hora, imovel_id,
        )
        self.sincronizar_status_do_lead(lead_id, db)
        db.refresh(agendamento)
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

        Cancelar ou dar por realizado o último compromisso de pé tira o lead de
        `agendado`, pelo mesmo motivo de `excluir`: o status afirma que existe
        visita ou reunião marcada. Confirmar não mexe em nada.
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
        self.sincronizar_status_do_lead(agendamento.lead_id, db)
        db.refresh(agendamento)
        return agendamento

    def excluir(self, agendamento_id: int, db: Session) -> bool:
        """Apaga o agendamento de vez.

        Diferente de marcar `cancelado`, que continua sendo o caminho quando a
        visita existiu e nao aconteceu: excluir e para o compromisso que nunca
        deveria ter sido criado — a data errada, o lead errado, o teste.

        Se este era o ultimo compromisso de pe, o lead sai de `agendado`: o
        status afirma que existe uma visita marcada, e apagar a ultima torna
        essa afirmacao falsa.
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
        self.sincronizar_status_do_lead(lead_id, db)
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
            self.sincronizar_status_do_lead(agendamento.lead_id, db)
            db.refresh(agendamento)
        return agendamento

    def get_pending_count(self, db: Session) -> int:
        """Retorna quantidade de agendamentos pendentes."""
        from sqlalchemy import func
        return (
            db.query(func.count(Agendamento.id))
            .filter(Agendamento.status == "pendente")
            .scalar() or 0
        )
