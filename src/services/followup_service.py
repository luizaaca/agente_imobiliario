"""Serviço de follow-up automático de leads inativos."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Lead, Mensagem, FollowUpAttempt

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


class FollowUpService:
    """Serviço de domínio para controle da régua de follow-up."""

    def get_eligible_leads(self, db: Session) -> List[Tuple[Lead, str]]:
        """Retorna leads elegíveis para follow-up com a régua aplicável.

        Returns:
            Lista de tuplas (lead, regua) para leads elegíveis.
        """
        eligible = []
        now = datetime.now(timezone.utc)

        for regua_name, config in REGUAS.items():
            if regua_name == "pos_agendamento":
                # Lógica especial: leads com agendamento próximo
                continue  # TODO: implementar quando houver agendamentos

            status_alvo = config["status_alvo"]
            inatividade_min = timedelta(hours=config["inatividade_minima_horas"])
            max_tentativas = config["max_tentativas"]

            # Buscar leads no status alvo
            leads = (
                db.query(Lead)
                .filter(Lead.status.in_(status_alvo))
                .all()
            )

            for lead in leads:
                # Verificar última mensagem
                last_msg = (
                    db.query(Mensagem)
                    .filter(Mensagem.lead_id == lead.id)
                    .order_by(Mensagem.timestamp.desc())
                    .first()
                )

                if not last_msg:
                    # Lead sem mensagens — usar created_at
                    last_activity = lead.created_at
                else:
                    last_activity = last_msg.timestamp

                # Verificar se a última atividade foi do lead (role=user)
                # Se a última mensagem for do assistente, o lead é que não respondeu
                if last_msg and last_msg.role == "user":
                    continue  # Lead respondeu, não precisa follow-up

                # Verificar inatividade mínima
                if last_activity and (now - last_activity) < inatividade_min:
                    continue  # Ainda não passou o tempo mínimo

                # Verificar máximo de tentativas
                attempts = self.get_attempts_count(lead.id, regua_name, db)
                if attempts >= max_tentativas:
                    continue  # Já atingiu o limite

                eligible.append((lead, regua_name))

        logger.info(f"Leads elegíveis para follow-up: {len(eligible)}")
        return eligible

    def determine_regua(self, lead: Lead, db: Session) -> Optional[str]:
        """Determina a régua de follow-up aplicável ao lead."""
        now = datetime.now(timezone.utc)

        for regua_name, config in REGUAS.items():
            if lead.status not in config["status_alvo"]:
                continue

            if regua_name == "pos_agendamento":
                continue  # TODO: tratar separadamente

            inatividade_min = timedelta(hours=config["inatividade_minima_horas"])
            max_tentativas = config["max_tentativas"]

            # Verificar última atividade
            last_msg = (
                db.query(Mensagem)
                .filter(Mensagem.lead_id == lead.id)
                .order_by(Mensagem.timestamp.desc())
                .first()
            )

            last_activity = last_msg.timestamp if last_msg else lead.created_at

            if last_activity and (now - last_activity) >= inatividade_min:
                attempts = self.get_attempts_count(lead.id, regua_name, db)
                if attempts < max_tentativas:
                    return regua_name

        return None

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
    ) -> FollowUpAttempt:
        """Registra uma tentativa de follow-up."""
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
        db.commit()
        db.refresh(attempt)

        logger.info(
            f"Follow-up registrado: lead_id={lead_id}, regua={regua}, "
            f"tentativa={attempt_number}, status={status}"
        )
        return attempt

    def get_regua_description(self, regua: str) -> str:
        """Retorna a descrição da régua."""
        config = REGUAS.get(regua, {})
        return config.get("descricao", regua)
