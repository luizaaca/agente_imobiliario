"""llm_usage registra status, tipo de erro e latencia

Revision ID: b1c4e7f20a13
Revises: a5da4466c608
Create Date: 2026-09-20

A tabela passa a registrar toda chamada ao provider, e nao so as que
consumiram token: sem a linha da falha, a taxa de erro do dashboard seria
sempre zero. As linhas ja existentes sao chamadas que deram certo, entao o
server_default 'ok' as classifica corretamente.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c4e7f20a13"
down_revision: str | None = "a5da4466c608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ok"
        ),
    )
    op.add_column(
        "llm_usage", sa.Column("error_type", sa.String(length=80), nullable=True)
    )
    op.add_column("llm_usage", sa.Column("latency_ms", sa.Integer(), nullable=True))
    # O dashboard filtra por dia e por status; sem o indice, cada carga varre a
    # tabela inteira.
    op.create_index(
        "ix_llm_usage_created_at_status", "llm_usage", ["created_at", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_created_at_status", table_name="llm_usage")
    op.drop_column("llm_usage", "latency_ms")
    op.drop_column("llm_usage", "error_type")
    op.drop_column("llm_usage", "status")
