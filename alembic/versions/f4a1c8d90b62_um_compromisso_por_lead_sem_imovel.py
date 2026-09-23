"""um compromisso ativo por lead, e sem vinculo com imovel

Duas mudancas na mesma tabela, pelo mesmo motivo: o compromisso deixa de
apontar para uma linha do catalogo e passa a ser um horario com o corretor.

1. `agendamentos.imovel_id` sai. Quem visita raramente visita um imovel so, e
   o vinculo unico obrigava a escolher um deles e perder o resto. Os imoveis
   de interesse passam a vir escritos na `observacoes`, com ID, que e o que o
   corretor le junto do perfil narrativo e do resumo executivo.

2. Um compromisso ativo por lead, cobrado por indice unico parcial. A regra
   morava so no codigo e nao se sustentou: a lead 29 chegou a ter duas visitas
   `pendente` ao mesmo tempo, marcadas em turnos diferentes, porque o modelo
   nao acertou o `agendamento_id` na hora de remarcar. Aqui o banco recusa.

Os compromissos ativos que sobram por lead sao cancelados antes do indice
subir, mantendo o mais recente — e o ultimo que a conversa pediu.

O downgrade devolve a coluna vazia: os vinculos nao sao preservados, por
decisao de quem pediu a mudanca. Oito dos nove ja descreviam o imovel na
propria `observacoes`.

Revision ID: f4a1c8d90b62
Revises: e3c7a94f1b05
Create Date: 2026-09-22 22:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'f4a1c8d90b62'
down_revision: str | None = 'e3c7a94f1b05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDICE = 'uq_agendamentos_ativo_por_lead'
STATUS_ATIVOS = "('pendente', 'confirmado')"


def upgrade() -> None:
    # Cancela o excedente antes de criar o indice, senao ele nao sobe. Fica o
    # de maior id: e o ultimo que a conversa pediu.
    op.execute(f"""
        UPDATE agendamentos SET status = 'cancelado'
        WHERE status IN {STATUS_ATIVOS}
          AND id NOT IN (
            SELECT max(id) FROM agendamentos
            WHERE status IN {STATUS_ATIVOS}
            GROUP BY lead_id
          )
    """)

    op.drop_constraint('fk_agendamentos_imovel_id', 'agendamentos', type_='foreignkey')
    op.drop_column('agendamentos', 'imovel_id')

    # Parcial: cancelado e realizado podem se repetir a vontade — sao o
    # historico do lead, e e dele que o corretor tira que a pessoa ja desmarcou.
    op.execute(f"""
        CREATE UNIQUE INDEX {INDICE}
        ON agendamentos (lead_id)
        WHERE status IN {STATUS_ATIVOS}
    """)


def downgrade() -> None:
    op.execute(f"DROP INDEX {INDICE}")
    op.add_column('agendamentos', sa.Column('imovel_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_agendamentos_imovel_id', 'agendamentos', 'imoveis', ['imovel_id'], ['id']
    )
