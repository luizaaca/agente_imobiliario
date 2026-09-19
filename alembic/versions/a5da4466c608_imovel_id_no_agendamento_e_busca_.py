"""imovel_id no agendamento e busca textual por tsvector

Duas mudancas:

1. `agendamentos.imovel_id` — a tool `agendar_reuniao` ja recebia o imovel do
   modelo, mas nao tinha onde guardar e o dado era descartado em silencio.

2. `imoveis.search_vector` — era uma coluna Text nunca preenchida, enquanto a
   busca caia em ILIKE ordenado por preco. Passa a ser uma coluna gerada
   (GENERATED ALWAYS ... STORED) com indice GIN, entao o PostgreSQL mantem o
   vetor atualizado sozinho, sem trigger nem codigo de aplicacao.

A expressao do tsvector esta escrita literalmente aqui, e nao importada de
`src.db.models`, para que esta migration continue reproduzindo este estado
historico mesmo que o modelo mude depois.

Revision ID: a5da4466c608
Revises: d7b2eeb2efcf
Create Date: 2026-09-19 19:07:43.506210

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'a5da4466c608'
down_revision: str | None = 'd7b2eeb2efcf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEARCH_VECTOR_EXPR = (
    "to_tsvector('portuguese'::regconfig, "
    "coalesce(titulo, '') || ' ' || "
    "coalesce(descricao, '') || ' ' || "
    "coalesce(tags, '') || ' ' || "
    "coalesce(bairro, '') || ' ' || "
    "coalesce(tipo, ''))"
)


def upgrade() -> None:
    op.add_column('agendamentos', sa.Column('imovel_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_agendamentos_imovel_id', 'agendamentos', 'imoveis', ['imovel_id'], ['id']
    )

    # Um ALTER TYPE nao transforma a coluna em gerada: e preciso recriar.
    # Nada se perde, a coluna Text nunca chegou a ser populada.
    op.drop_column('imoveis', 'search_vector')
    op.add_column(
        'imoveis',
        sa.Column(
            'search_vector',
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPR, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_imoveis_search_vector', 'imoveis', ['search_vector'],
        unique=False, postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('ix_imoveis_search_vector', table_name='imoveis', postgresql_using='gin')
    op.drop_column('imoveis', 'search_vector')
    op.add_column('imoveis', sa.Column('search_vector', sa.Text(), nullable=True))

    op.drop_constraint('fk_agendamentos_imovel_id', 'agendamentos', type_='foreignkey')
    op.drop_column('agendamentos', 'imovel_id')
