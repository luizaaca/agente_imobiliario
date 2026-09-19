"""Serviço para geração de resumo executivo do corretor."""

import logging

from sqlalchemy.orm import Session

from src.db.models import Lead, Mensagem

logger = logging.getLogger(__name__)


class SummaryService:
    """Serviço de composição de resumo executivo para handover ao corretor."""

    def build_context(self, lead_id: int, db: Session) -> dict:
        """Constrói o contexto completo do lead para geração de resumo."""
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return {}

        messages = (
            db.query(Mensagem)
            .filter(Mensagem.lead_id == lead_id)
            .order_by(Mensagem.timestamp.desc())
            .limit(50)
            .all()
        )

        return {
            "lead": lead,
            "messages": list(reversed(messages)),
            "total_messages": len(messages),
            "user_messages": sum(1 for m in messages if m.role == "user"),
        }

    def generate_resumo(self, lead_id: int, db: Session) -> str:
        """Gera o resumo executivo textual para o corretor.

        Esta função compõe o texto do resumo a partir dos dados do lead.
        A geração via LLM, quando necessária, ocorre na camada do agente.
        """
        context = self.build_context(lead_id, db)
        if not context:
            return "Lead não encontrado."

        lead = context["lead"]

        # Compor resumo estruturado
        sections = []

        # Cabeçalho
        sections.append(
            f"## Resumo Executivo — {lead.nome or f'Lead {lead.id}'}"
        )

        # Dados de qualificação
        sections.append("### Qualificação")
        sections.append(f"- **Intenção:** {lead.intencao or 'não informada'}")
        sections.append(
            f"- **Orçamento:** R$ {lead.orcamento_min or '?'} "
            f"a R$ {lead.orcamento_max or '?'}"
        )
        sections.append(
            f"- **Região:** {lead.regiao_interesse or lead.bairro_interesse or 'não informada'}"
        )
        sections.append(f"- **Quartos:** {lead.quartos or 'não informado'}")
        sections.append(f"- **Urgência:** {lead.urgencia or 'não informada'}")
        sections.append(f"- **Forma de pagamento:** {lead.forma_pagamento or 'não informada'}")
        sections.append(f"- **Motivo da busca:** {lead.motivo_busca or 'não informado'}")

        # Score
        sections.append("### Score e Status")
        sections.append(f"- **Score:** {lead.score or 'não calculado'}/10")
        sections.append(f"- **Status:** {lead.status}")

        # Interpretação do score
        score_val = float(lead.score or 0)
        if score_val >= 9:
            interpretacao = "🔴 Lead muito quente — alta prioridade"
        elif score_val >= 7:
            interpretacao = "🔴 Lead quente — contato prioritário"
        elif score_val >= 4:
            interpretacao = "🟠 Lead em qualificação — potencial moderado"
        else:
            interpretacao = "⚪ Lead frio — pouco qualificado"
        sections.append(f"- **Interpretação:** {interpretacao}")

        # Perfil narrativo
        if lead.perfil_narrativo:
            sections.append("### Perfil Narrativo Completo")
            sections.append(lead.perfil_narrativo)

        # Engajamento
        sections.append("### Engajamento")
        sections.append(
            f"- Total de mensagens: {context['total_messages']}"
        )
        sections.append(
            f"- Mensagens do lead: {context['user_messages']}"
        )

        # Próximos passos
        sections.append("### Próximos Passos Sugeridos")
        if lead.status == "agendado":
            sections.append("- ✅ Lead já possui agendamento. Confirmar visita/reunião.")
        elif score_val >= 7:
            sections.append("- 📞 Priorizar contato direto. Lead qualificado.")
            sections.append("- 🏠 Preparar opções de imóveis para apresentação.")
        elif score_val >= 4:
            sections.append("- 💬 Continuar qualificação via conversa.")
            sections.append("- 🔍 Buscar imóveis compatíveis com o perfil parcial.")
        else:
            sections.append("- ⏳ Aguardar mais dados antes de investir tempo.")
            sections.append("- 🔄 Considerar follow-up se inativo.")

        return "\n".join(sections)
