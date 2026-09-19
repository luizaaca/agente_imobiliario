"""Serviço para gestão de leads."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from src.db.models import Lead, LeadChannelIdentity, Mensagem
from src.schemas.lead import LeadStatus

logger = logging.getLogger(__name__)


# Limites de tamanho lidos do próprio modelo, para não duplicar o schema aqui.
LIMITES_DE_TEXTO = {
    coluna.name: coluna.type.length
    for coluna in Lead.__table__.columns
    if getattr(coluna.type, "length", None)
}

# Campos com vocabulário fechado no banco (CHECK constraints). Um valor fora
# da lista derrubaria o INSERT, então é descartado antes de chegar lá.
VALORES_PERMITIDOS = {
    "intencao": {"compra", "aluguel", "investimento"},
    "urgencia": {"baixa", "media", "alta"},
}


class LeadService:
    """Serviço de domínio para gestão de leads."""

    def sanitizar_qualificacao(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ajusta os dados vindos da LLM aos limites do banco.

        As tools recebem texto livre de um modelo de linguagem; sem esta
        barreira, um valor fora do vocabulário ou maior que a coluna derruba o
        turno inteiro com DataError/IntegrityError.
        """
        limpo: Dict[str, Any] = {}

        for campo, valor in data.items():
            if not isinstance(valor, str):
                limpo[campo] = valor
                continue

            valor = valor.strip()

            permitidos = VALORES_PERMITIDOS.get(campo)
            if permitidos:
                normalizado = valor.lower()
                if normalizado not in permitidos:
                    logger.warning(
                        "event=valor_fora_do_vocabulario campo=%s valor=%r "
                        "permitidos=%s acao=descartado",
                        campo, valor[:60], sorted(permitidos),
                    )
                    continue
                valor = normalizado

            limite = LIMITES_DE_TEXTO.get(campo)
            if limite and len(valor) > limite:
                logger.warning(
                    "event=valor_truncado campo=%s tamanho=%s limite=%s valor=%r",
                    campo, len(valor), limite, valor[:60],
                )
                valor = valor[:limite]

            limpo[campo] = valor

        return limpo

    def get_or_create_lead(
        self,
        channel: str,
        external_id: str,
        db: Session,
        nome: Optional[str] = None,
    ) -> Lead:
        """Busca lead existente ou cria um novo para o canal."""
        identity = (
            db.query(LeadChannelIdentity)
            .filter_by(channel=channel, external_chat_id=external_id)
            .first()
        )

        if identity:
            identity.last_seen_at = func.now()
            if nome and not identity.lead.nome:
                identity.lead.nome = nome
            db.commit()
            return identity.lead

        lead = Lead(
            status=LeadStatus.NOVO.value,
            score=Decimal("0.0"),
            canal_origem=channel,
            nome=nome,
        )
        db.add(lead)
        db.flush()

        new_identity = LeadChannelIdentity(
            lead_id=lead.id,
            channel=channel,
            external_chat_id=external_id,
            is_primary=True,
        )
        db.add(new_identity)
        db.commit()
        db.refresh(lead)
        return lead

    def get_lead(self, lead_id: int, db: Session) -> Optional[Lead]:
        """Busca um lead pelo ID."""
        return db.query(Lead).filter(Lead.id == lead_id).first()

    def update_qualification(
        self, lead_id: int, data: Dict[str, Any], db: Session
    ) -> Optional[Lead]:
        """Atualiza os dados de qualificação de um lead."""
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        for key, value in self.sanitizar_qualificacao(data).items():
            if hasattr(lead, key) and value is not None:
                setattr(lead, key, value)

        lead.status = self.avaliar_status(lead)

        db.commit()
        db.refresh(lead)
        return lead

    # Dados mínimos que caracterizam um lead qualificado: sem eles o corretor
    # não consegue trabalhar a oportunidade.
    CAMPOS_DE_QUALIFICACAO = (
        ("intencao",),
        ("orcamento_min", "orcamento_max"),
        ("bairro_interesse", "regiao_interesse"),
        ("quartos",),
    )

    def esta_qualificado(self, lead: Lead) -> bool:
        """Indica se o lead já tem os dados mínimos de qualificação."""
        return all(
            any(getattr(lead, campo, None) is not None for campo in grupo)
            for grupo in self.CAMPOS_DE_QUALIFICACAO
        )

    def avaliar_status(self, lead: Lead) -> str:
        """Calcula o status do lead no funil a partir dos dados coletados.

        Só avança leads ainda em coleta: quem já agendou não regride, e quem
        está inativo só volta ao funil quando responde (ver process_message).
        """
        if lead.status not in (LeadStatus.NOVO.value, LeadStatus.EM_QUALIFICACAO.value):
            return lead.status

        if self.esta_qualificado(lead):
            return LeadStatus.QUALIFICADO.value

        return LeadStatus.EM_QUALIFICACAO.value

    def update_perfil_narrativo(
        self, lead_id: int, novo_texto: str, db: Session
    ) -> Optional[Lead]:
        """Atualiza o perfil narrativo do lead.

        Recebe o texto completo atualizado (não incremental),
        pois a LLM é responsável por manter a coerência do perfil.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        lead.perfil_narrativo = novo_texto
        db.commit()
        db.refresh(lead)
        logger.info(f"Perfil narrativo atualizado para lead {lead_id}")
        return lead

    def calculate_score(self, lead_id: int, db: Session) -> Decimal:
        """Calcula o score do lead baseado em 5 dimensões.

        Dimensões e pesos:
        1. Completude dos dados: até 3.0
        2. Urgência declarada: até 2.0
        3. Aderência com catálogo: até 2.0
        4. Engajamento conversacional: até 1.5
        5. Intenção de agendamento: até 1.5
        Total máximo: 10.0
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return Decimal("0.0")

        score = 0.0

        # 1. Completude dos dados (até 3.0)
        campos_preenchidos = 0
        if lead.intencao:
            campos_preenchidos += 1
        if lead.orcamento_min or lead.orcamento_max:
            campos_preenchidos += 1
        if lead.bairro_interesse or lead.regiao_interesse:
            campos_preenchidos += 1
        if lead.quartos is not None:
            campos_preenchidos += 1
        if lead.urgencia:
            campos_preenchidos += 1

        if campos_preenchidos >= 5:
            score += 3.0
        elif campos_preenchidos >= 3:
            score += 2.5
        elif campos_preenchidos >= 2:
            score += 1.5
        elif campos_preenchidos >= 1:
            score += 0.5

        # 2. Urgência declarada (até 2.0)
        if lead.urgencia == "alta":
            score += 2.0
        elif lead.urgencia == "media":
            score += 1.0
        elif lead.urgencia == "baixa":
            score += 0.5

        # 3. Aderência com catálogo (até 2.0)
        if lead.tipologia_interesse:
            score += 1.0
        if lead.forma_pagamento:
            score += 1.0

        # 4. Engajamento conversacional (até 1.5)
        msg_count = (
            db.query(func.count(Mensagem.id))
            .filter(
                Mensagem.lead_id == lead.id,
                Mensagem.role == "user",
            )
            .scalar() or 0
        )
        if msg_count > 10:
            score += 1.5
        elif msg_count > 5:
            score += 1.0
        elif msg_count > 0:
            score += 0.5

        # 5. Intenção de agendamento (até 1.5)
        agendamentos_count = len(lead.agendamentos) if lead.agendamentos else 0
        if agendamentos_count > 0:
            score += 1.5

        final_score = min(10.0, max(0.0, score))
        lead.score = Decimal(str(round(final_score, 2)))
        db.commit()

        return lead.score

    def update_status(
        self, lead_id: int, new_status: str, db: Session
    ) -> None:
        """Atualiza o status de um lead."""
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead:
            lead.status = new_status
            db.commit()

    def save_message(
        self,
        lead_id: int,
        channel: str,
        role: str,
        content: str,
        message_type: str,
        db: Session,
        status: str = "created",
    ) -> Mensagem:
        """Salva uma mensagem no histórico."""
        msg = Mensagem(
            lead_id=lead_id,
            channel=channel,
            role=role,
            content=content,
            message_type=message_type,
            status=status,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg

    def mark_message_sent(self, message_id: int, db: Session) -> None:
        """Marca uma mensagem como efetivamente enviada ao canal."""
        msg = db.query(Mensagem).filter(Mensagem.id == message_id).first()
        if msg:
            msg.status = "sent"
            msg.sent_at = datetime.now(timezone.utc)
            db.commit()

    def get_latest_identity_by_prefix(
        self, channel: str, prefix: str, db: Session
    ) -> Optional[LeadChannelIdentity]:
        """Identidade mais recente de um canal cujo external_id casa o prefixo.

        Usada pela UI para retomar a última conversa do usuário após um
        refresh da página, em vez de abrir um lead novo a cada carregamento.
        """
        return (
            db.query(LeadChannelIdentity)
            .filter(
                LeadChannelIdentity.channel == channel,
                # autoescape: o prefixo contém '_', que em LIKE é curinga de
                # um caractere e casaria identidades de outros usuários.
                LeadChannelIdentity.external_chat_id.startswith(
                    prefix, autoescape=True
                ),
            )
            .order_by(LeadChannelIdentity.id.desc())
            .first()
        )

    def get_primary_identity(
        self, lead_id: int, db: Session
    ) -> Optional[LeadChannelIdentity]:
        """Identidade de canal preferencial do lead, para envio ativo."""
        return (
            db.query(LeadChannelIdentity)
            .filter(LeadChannelIdentity.lead_id == lead_id)
            .order_by(LeadChannelIdentity.is_primary.desc(), LeadChannelIdentity.id)
            .first()
        )

    def has_message_type(
        self, lead_id: int, message_type: str, db: Session
    ) -> bool:
        """Indica se o lead já possui alguma mensagem do tipo informado."""
        return (
            db.query(Mensagem.id)
            .filter(
                Mensagem.lead_id == lead_id,
                Mensagem.message_type == message_type,
            )
            .first()
            is not None
        )

    def get_history(
        self, lead_id: int, limit: int, db: Session
    ) -> List[Mensagem]:
        """Recupera as últimas mensagens de um lead, ordenadas cronologicamente."""
        messages = (
            db.query(Mensagem)
            .filter(Mensagem.lead_id == lead_id)
            .order_by(Mensagem.timestamp.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(messages))

    def get_leads_for_dashboard(
        self, filters: Dict[str, Any], db: Session
    ) -> List[Lead]:
        """Busca leads para o painel do corretor com filtros."""
        query = db.query(Lead)

        if filters.get("status"):
            query = query.filter(Lead.status == filters["status"])
        if filters.get("intencao"):
            query = query.filter(Lead.intencao == filters["intencao"])

        return query.order_by(Lead.score.desc().nullslast()).limit(50).all()
