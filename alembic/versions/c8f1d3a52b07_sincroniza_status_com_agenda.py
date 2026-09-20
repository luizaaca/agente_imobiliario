"""sincroniza o status dos leads com os agendamentos existentes

Revision ID: c8f1d3a52b07
Revises: b1c4e7f20a13
Create Date: 2026-09-20

Migracao de dados, sem mudanca de esquema. `agendado` afirma que existe visita
ou reuniao de pe; ate agora nada desfazia essa afirmacao quando o ultimo
compromisso era apagado ou cancelado, entao sobraram leads marcados como
agendados sem ter agenda nenhuma — e o KPI de agendamentos contava
compromissos que nao existiam.

O codigo passou a sincronizar nos dois sentidos, mas so quando um agendamento
muda. As linhas que ja estavam erradas nao tem esse gatilho, e e o que esta
correcao resolve.

O criterio do `CASE` e o mesmo de `LeadService.esta_qualificado`: intencao,
alguma ponta de orcamento, alguma localizacao e quartos. Leads `inativo`
ficam de fora — quem parou de responder continua parado.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "c8f1d3a52b07"
down_revision: str | None = "b1c4e7f20a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATIVOS = "('pendente', 'confirmado')"


def upgrade() -> None:
    # Marcados como agendados, mas sem compromisso de pe.
    op.execute(
        f"""
        UPDATE leads SET status = CASE
            WHEN intencao IS NOT NULL
             AND (orcamento_min IS NOT NULL OR orcamento_max IS NOT NULL)
             AND (bairro_interesse IS NOT NULL OR regiao_interesse IS NOT NULL)
             AND quartos IS NOT NULL
            THEN 'qualificado'
            ELSE 'em_qualificacao'
        END
        WHERE status = 'agendado'
          AND NOT EXISTS (
              SELECT 1 FROM agendamentos a
              WHERE a.lead_id = leads.id AND a.status IN {_ATIVOS}
          )
        """
    )
    # Com compromisso de pe, mas parados em outro estagio do funil.
    op.execute(
        f"""
        UPDATE leads SET status = 'agendado'
        WHERE status IN ('novo', 'em_qualificacao', 'qualificado')
          AND EXISTS (
              SELECT 1 FROM agendamentos a
              WHERE a.lead_id = leads.id AND a.status IN {_ATIVOS}
          )
        """
    )


def downgrade() -> None:
    """Sem volta: o estado anterior era justamente o inconsistente."""
