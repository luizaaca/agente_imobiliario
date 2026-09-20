"""Serviço de follow-up automático de leads inativos."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Agendamento, FollowUpAttempt, Lead, Mensagem

logger = logging.getLogger(__name__)

# Configuração das réguas de follow-up
REGUAS = {
    "lead_novo_sem_resposta": {
        "descricao": "Lead novo sem resposta",
        "inatividade_minima_horas": 2,
        "max_tentativas": 3,
        "status_alvo": ["novo"],
    },
    "qualificacao_interrompida": {
        "descricao": "Qualificação interrompida",
        "inatividade_minima_horas": 6,
        "max_tentativas": 3,
        "status_alvo": ["em_qualificacao"],
    },
    "pos_envio_imoveis": {
        "descricao": "Pós-envio de imóveis",
        "inatividade_minima_horas": 24,
        "max_tentativas": 2,
        "status_alvo": ["qualificado"],
    },
    "pos_agendamento": {
        "descricao": "Pós-agendamento (confirmação/lembrete)",
        "antecedencia_horas": 24,
        "max_tentativas": 2,
        "status_alvo": ["agendado"],
    },
}

# Réguas baseadas em silêncio do lead: esgotar as tentativas significa que o
# lead parou de responder. A pós-agendamento é um lembrete, não um resgate,
# então nunca marca o lead como inativo.
REGUAS_DE_INATIVIDADE = {
    nome for nome, cfg in REGUAS.items() if "inatividade_minima_horas" in cfg
}


class FollowUpService:
    """Serviço de domínio para controle da régua de follow-up."""

    def get_eligible_leads(self, db: Session) -> list[tuple[Lead, str]]:
        """Retorna leads elegíveis para follow-up com a régua aplicável.

        Returns:
            Lista de tuplas (lead, regua) para leads elegíveis.
        """
        eligible: list[tuple[Lead, str]] = []
        now = datetime.now(UTC)
        ja_selecionados: set[int] = set()

        for regua_name, config in REGUAS.items():
            if regua_name == "pos_agendamento":
                candidatos = self._leads_com_agendamento_proximo(now, config, db)
            else:
                candidatos = self._leads_inativos(now, config, db)

            for lead in candidatos:
                # Um lead recebe no máximo uma régua por ciclo.
                if lead.id in ja_selecionados:
                    continue
                if self.get_attempts_count(lead.id, regua_name, db) >= config["max_tentativas"]:
                    continue

                ja_selecionados.add(lead.id)
                eligible.append((lead, regua_name))

        logger.info(
            "event=followup_leads_elegiveis quantidade=%s", len(eligible)
        )
        return eligible

    def _leads_inativos(
        self, now: datetime, config: dict, db: Session
    ) -> list[Lead]:
        """Leads no status alvo que estão calados há tempo suficiente."""
        inatividade_min = timedelta(hours=config["inatividade_minima_horas"])
        candidatos = []

        leads = db.query(Lead).filter(Lead.status.in_(config["status_alvo"])).all()
        for lead in leads:
            last_msg = (
                db.query(Mensagem)
                .filter(Mensagem.lead_id == lead.id)
                .order_by(Mensagem.timestamp.desc(), Mensagem.id.desc())
                .first()
            )

            # Se a última mensagem é do lead, a bola está conosco: ele
            # respondeu e o que falta é uma resposta, não um follow-up.
            if last_msg and last_msg.role == "user":
                continue

            last_activity = last_msg.timestamp if last_msg else lead.created_at
            if last_activity and (now - last_activity) < inatividade_min:
                continue

            candidatos.append(lead)

        return candidatos

    def _leads_com_agendamento_proximo(
        self, now: datetime, config: dict, db: Session
    ) -> list[Lead]:
        """Leads com visita/reunião dentro da janela de antecedência."""
        limite = now + timedelta(hours=config["antecedencia_horas"])

        return (
            db.query(Lead)
            .join(Agendamento, Agendamento.lead_id == Lead.id)
            .filter(
                Lead.status.in_(config["status_alvo"]),
                Agendamento.status.in_(["pendente", "confirmado"]),
                Agendamento.data_hora > now,
                Agendamento.data_hora <= limite,
            )
            .distinct()
            .all()
        )

    def get_attempts_count(
        self, lead_id: int, regua: str, db: Session
    ) -> int:
        """Retorna a quantidade de tentativas de follow-up para uma régua."""
        return (
            db.query(func.count(FollowUpAttempt.id))
            .filter(
                FollowUpAttempt.lead_id == lead_id,
                FollowUpAttempt.regua == regua,
            )
            .scalar() or 0
        )

    def record_attempt(
        self,
        lead_id: int,
        regua: str,
        status: str,
        db: Session,
        message_id: Optional[int] = None,
        failure_reason: Optional[str] = None,
    ) -> Optional[FollowUpAttempt]:
        """Registra uma tentativa de follow-up.

        Retorna None quando a tentativa já foi registrada por outra execução
        concorrente — a constraint única (lead_id, regua, attempt_number) é a
        garantia de que a mesma régua não dispara duas vezes na mesma janela.
        """
        attempt_number = self.get_attempts_count(lead_id, regua, db) + 1

        attempt = FollowUpAttempt(
            lead_id=lead_id,
            message_id=message_id,
            regua=regua,
            attempt_number=attempt_number,
            status=status,
            failure_reason=failure_reason,
        )
        db.add(attempt)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning(
                "event=followup_duplicado lead_id=%s regua=%s tentativa=%s "
                "detalhe=execucao_concorrente_ignorada",
                lead_id, regua, attempt_number,
            )
            return None

        db.refresh(attempt)
        logger.info(
            "event=followup_tentativa_registrada lead_id=%s regua=%s "
            "tentativa=%s status=%s",
            lead_id, regua, attempt_number, status,
        )
        return attempt

    def tentativas_esgotadas(
        self, lead_id: int, regua: str, db: Session
    ) -> bool:
        """Indica se a régua já consumiu todas as tentativas do lead."""
        config = REGUAS.get(regua)
        if not config:
            return False
        return self.get_attempts_count(lead_id, regua, db) >= config["max_tentativas"]

    def deve_marcar_inativo(
        self, lead_id: int, regua: str, db: Session
    ) -> bool:
        """Lead que esgotou uma régua de silêncio deve sair do funil ativo."""
        return (
            regua in REGUAS_DE_INATIVIDADE
            and self.tentativas_esgotadas(lead_id, regua, db)
        )

    def get_regua_description(self, regua: str) -> str:
        """Retorna a descrição da régua."""
        config = REGUAS.get(regua, {})
        return config.get("descricao", regua)
