"""Serviço para agendamento de visitas e reuniões."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Agendamento, Lead
from src.schemas.lead import LeadStatus
from src.services.lead_service import LeadService
from src.tempo import formatar

logger = logging.getLogger(__name__)


class CompromissoJaMarcado(Exception):
    """Este lead já tem um compromisso de pé, e só se permite um.

    Carrega o compromisso existente porque quem trata isto precisa dizer qual
    é: ao modelo, para ele combinar a troca com a pessoa antes de insistir; ao
    corretor, para ele ver na tela o que já está marcado.
    """

    def __init__(self, existente):
        self.existente = existente
        super().__init__(
            f"Lead {existente.lead_id} já tem {existente.tipo} em "
            f"{formatar(existente.data_hora)}."
        )


def _com_nota(observacoes: Optional[str], nota: str) -> str:
    """Acrescenta uma linha à observação sem apagar o que já estava escrito."""
    anterior = (observacoes or "").strip()
    return f"{anterior}\n{nota}".strip()


class SchedulingService:
    """Serviço de domínio para agendamentos."""

    STATUS_VALIDOS = ("pendente", "confirmado", "cancelado", "realizado")
    TIPOS_VALIDOS = ("visita", "reuniao")
    # Compromissos que ainda estao de pe. `realizado` sai da lista junto com
    # `cancelado`: a visita ja aconteceu, e o lead nao esta mais esperando por
    # ela.
    STATUS_ATIVOS = ("pendente", "confirmado")

    def compromisso_ativo(self, lead_id: int, db: Session) -> Optional[Agendamento]:
        """O compromisso de pé deste lead, ou `None`.

        No máximo um, e não por convenção: há índice único parcial sobre
        `lead_id` para os status ativos. A regra morava só aqui no código e
        não se sustentou — um lead chegou a ter duas visitas pendentes ao
        mesmo tempo, marcadas em turnos diferentes.
        """
        return (
            db.query(Agendamento)
            .filter(
                Agendamento.lead_id == lead_id,
                Agendamento.status.in_(self.STATUS_ATIVOS),
            )
            .first()
        )

    def tem_compromisso_ativo(self, lead_id: int, db: Session) -> bool:
        """Se existe visita ou reuniao de pe para este lead."""
        return self.compromisso_ativo(lead_id, db) is not None

    def sincronizar_lead_com_a_agenda(
        self, lead_id: int, db: Session
    ) -> Optional[str]:
        """Faz status e score do lead concordarem com os compromissos dele.

        Os dois fatos que a agenda determina saem daqui juntos, e não de cada
        chamador. Enquanto o score ficava por conta de quem lembrasse, marcar
        a visita não recalculava nada: o lead com visita na agenda carregava a
        nota de antes de ela existir e empatava com quem já tinha parado de
        responder.

        `agendado` não é opinião, é fato verificável: ou existe visita
        marcada, ou não existe. Por isso a sincronização vale nos dois
        sentidos — aparecendo compromisso o lead vai para `agendado`, sumindo
        o último ele volta para onde os dados o colocam.

        Os outros estágios são julgamento de quem atende e não são tocados
        aqui; `inativo` também fica de fora, porque um lead que parou de
        responder continua parado mesmo com uma visita antiga no calendário.
        O score não tem essa ressalva: quem cancelou a visita perde o ponto
        dela mesmo estando inativo, senão o número mente para sempre.

        Devolve o novo status quando houve mudança, e `None` quando já estava
        certo — é o que permite a quem chama saber se precisa avisar na tela.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead is None:
            return None

        LeadService().calculate_score(lead_id, db)
        if lead.status == LeadStatus.INATIVO.value:
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
        remarcar: bool = False,
    ) -> Agendamento:
        """Marca o compromisso do lead. Um de pé por vez.

        Pedir de novo exatamente o mesmo horário devolve o que já existe, em
        vez de recusar: é o que o duplo clique na tela faz, e é o que o modelo
        faz quando repete a chamada sem ter lido o retorno da primeira.

        Horário diferente com compromisso de pé é outra coisa, e não se
        resolve sozinho — pode ser remarcação, pode ser o modelo esquecendo o
        que já marcou. Por isso levanta `CompromissoJaMarcado`, e só remarca
        quem disser `remarcar=True`, depois de ter combinado com a pessoa.

        Remarcar cancela e cria, em vez de mover a linha: o corretor precisa
        ver que a data mudou, e uma linha só reescrita apagaria o fato de que
        a pessoa já desmarcou uma vez — que é informação de venda.
        """
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo de agendamento inválido: {tipo}")

        ativo = self.compromisso_ativo(lead_id, db)
        if ativo is not None:
            if ativo.tipo == tipo and ativo.data_hora == data_hora:
                logger.info(
                    "event=agendamento_ja_existia lead_id=%s agendamento_id=%s "
                    "data_hora=%s acao=reaproveitado",
                    lead_id, ativo.id, data_hora,
                )
                return ativo
            if not remarcar:
                raise CompromissoJaMarcado(ativo)
            self._cancelar_por_remarcacao(ativo, data_hora, db)

        agendamento = Agendamento(
            lead_id=lead_id,
            tipo=tipo,
            data_hora=data_hora,
            observacoes=observacoes,
            status="pendente",
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        logger.info(
            "event=agendamento_criado lead_id=%s agendamento_id=%s tipo=%s "
            "data_hora=%s remarcacao=%s status=ok",
            lead_id, agendamento.id, tipo, data_hora, ativo is not None,
        )
        self.sincronizar_lead_com_a_agenda(lead_id, db)
        db.refresh(agendamento)
        return agendamento

    @staticmethod
    def _cancelar_por_remarcacao(
        antigo: Agendamento, nova_data: datetime, db: Session
    ) -> None:
        """Encerra o compromisso antigo dizendo, na ficha, que ele foi movido.

        Sem a nota, o corretor abre a agenda e vê um cancelamento: conclui que
        a pessoa desistiu, quando ela só trocou de dia.
        """
        antigo.status = "cancelado"
        antigo.observacoes = _com_nota(
            antigo.observacoes, f"Remarcado para {formatar(nova_data)}."
        )
        db.commit()
        logger.info(
            "event=agendamento_remarcado agendamento_id=%s lead_id=%s "
            "nova_data=%s",
            antigo.id, antigo.lead_id, nova_data,
        )

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
    ) -> Optional[Agendamento]:
        """Reescreve um agendamento com o que o corretor deixou na ficha.

        Grava todos os campos, inclusive os vazios: aqui `None` significa "o
        corretor apagou", e não "não foi informado". É o mesmo critério da
        edição de lead — o caminho manual precisa conseguir limpar o que veio
        errado da conversa.

        Cancelar ou dar por realizado o último compromisso de pé tira o lead de
        `agendado`, pelo mesmo motivo de `excluir`: o status afirma que existe
        visita ou reunião marcada. Confirmar não mexe em nada.

        Ressuscitar um compromisso cancelado enquanto outro está de pé levanta
        `CompromissoJaMarcado`. Sem esta checagem o índice único recusaria o
        `UPDATE` e o corretor veria um erro de banco no lugar do motivo.
        """
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo de agendamento inválido: {tipo}")
        if status not in self.STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {status}")

        agendamento = self.get(agendamento_id, db)
        if not agendamento:
            return None

        if status in self.STATUS_ATIVOS:
            ativo = self.compromisso_ativo(agendamento.lead_id, db)
            if ativo is not None and ativo.id != agendamento_id:
                raise CompromissoJaMarcado(ativo)

        agendamento.tipo = tipo
        agendamento.data_hora = data_hora
        agendamento.status = status
        agendamento.observacoes = observacoes

        db.commit()
        db.refresh(agendamento)
        logger.info(
            "event=agendamento_editado agendamento_id=%s lead_id=%s tipo=%s "
            "data_hora=%s status=%s",
            agendamento_id, agendamento.lead_id, tipo, data_hora, status,
        )
        self.sincronizar_lead_com_a_agenda(agendamento.lead_id, db)
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
        self.sincronizar_lead_com_a_agenda(lead_id, db)
        return True

    def update_status(
        self,
        agendamento_id: int,
        status: str,
        db: Session,
    ) -> Optional[Agendamento]:
        """Atualiza o status de um agendamento.

        Devolver um compromisso encerrado à ativa enquanto outro está de pé
        levanta `CompromissoJaMarcado`: só se permite um por lead, e sem esta
        checagem o índice único recusaria o `UPDATE` com erro de banco.
        """
        if status not in self.STATUS_VALIDOS:
            raise ValueError(
                f"Status inválido: {status}. Válidos: {self.STATUS_VALIDOS}"
            )

        agendamento = db.query(Agendamento).filter(
            Agendamento.id == agendamento_id
        ).first()
        if agendamento:
            if status in self.STATUS_ATIVOS:
                ativo = self.compromisso_ativo(agendamento.lead_id, db)
                if ativo is not None and ativo.id != agendamento_id:
                    raise CompromissoJaMarcado(ativo)
            agendamento.status = status
            db.commit()
            db.refresh(agendamento)
            logger.info(
                "event=agendamento_atualizado agendamento_id=%s lead_id=%s "
                "novo_status=%s",
                agendamento_id, agendamento.lead_id, status,
            )
            self.sincronizar_lead_com_a_agenda(agendamento.lead_id, db)
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
