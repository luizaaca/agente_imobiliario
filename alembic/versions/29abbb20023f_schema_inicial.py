"""schema inicial

Revision ID: 29abbb20023f
Revises:
Create Date: 2026-09-23

O esquema inteiro numa migration so. A POC ainda nao foi para lugar nenhum, e
uma cadeia de correcoes sobre uma modelagem que mudou no meio do caminho conta
a historia do desenvolvimento, nao o estado do banco — quem chega agora quer
ler o segundo.

Duas coisas aqui nao sao DDL comum e explicam-se sozinhas mal:

1. `imoveis.search_vector` e coluna GERADA (`GENERATED ALWAYS ... STORED`), com
   indice GIN. O PostgreSQL mantem o vetor atualizado sozinho, sem trigger nem
   codigo de aplicacao, e a busca textual do agente depende disso.

2. `uq_agendamentos_ativo_por_lead` e indice unico PARCIAL: um compromisso de
   pe por lead, enquanto `cancelado` e `realizado` se repetem a vontade. Sao o
   historico de onde o corretor tira que a pessoa ja desmarcou uma vez.

A role `busca_ro` sobe no fim, depois de `imoveis` existir. Ela e a fronteira
que o agente de busca nao atravessa: recebe SELECT nessa tabela e nada mais.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "29abbb20023f"
down_revision: str | None = None
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

COMPROMISSO_ATIVO = "status IN ('pendente', 'confirmado')"

# Escritas literalmente, e nao importadas de `src.config`, para esta migration
# continuar reproduzindo este estado mesmo que a configuracao mude depois.
ROLE = "busca_ro"
SENHA_PADRAO = "busca_ro_dev_pass"


def upgrade() -> None:
    op.create_table(
        "imoveis",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("finalidade", sa.String(length=20), nullable=False),
        sa.Column("operacao", sa.String(length=20), nullable=False),
        sa.Column("bairro", sa.String(length=100), nullable=False),
        sa.Column("zona", sa.String(length=50), nullable=True),
        sa.Column("cidade", sa.String(length=100), nullable=False),
        sa.Column("estado", sa.String(length=2), nullable=False),
        sa.Column("preco", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("quartos", sa.SmallInteger(), nullable=False),
        sa.Column("suites", sa.SmallInteger(), nullable=True),
        sa.Column("banheiros", sa.SmallInteger(), nullable=True),
        sa.Column("vaga_garagem", sa.SmallInteger(), nullable=True),
        sa.Column("area_m2", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("condominio", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("iptu_anual", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("perfil_indicado", sa.String(length=30), nullable=True),
        sa.Column("disponivel", sa.Boolean(), nullable=False),
        sa.Column("imagem_url", sa.String(length=500), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPR, persisted=True),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "finalidade IN ('residencial','comercial')", name="check_finalidade"),
        sa.CheckConstraint("operacao IN ('venda','aluguel')", name="check_operacao"),
        sa.CheckConstraint("area_m2 > 0", name="check_area"),
        sa.CheckConstraint("banheiros >= 0", name="check_banheiros"),
        sa.CheckConstraint("condominio >= 0", name="check_condominio"),
        sa.CheckConstraint("iptu_anual >= 0", name="check_iptu"),
        sa.CheckConstraint("preco > 0", name="check_preco"),
        sa.CheckConstraint("quartos >= 0", name="check_imovel_quartos"),
        sa.CheckConstraint("suites >= 0", name="check_suites"),
        sa.CheckConstraint("vaga_garagem >= 0", name="check_vagas"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_imoveis_search_vector", "imoveis", ["search_vector"],
        unique=False, postgresql_using="gin",
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=True),
        sa.Column("telefone", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("intencao", sa.String(length=30), nullable=True),
        sa.Column("tipologia_interesse", sa.String(length=30), nullable=True),
        sa.Column("orcamento_min", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("orcamento_max", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("forma_pagamento", sa.String(length=30), nullable=True),
        sa.Column("regiao_interesse", sa.String(length=80), nullable=True),
        sa.Column("bairro_interesse", sa.String(length=80), nullable=True),
        sa.Column("quartos", sa.SmallInteger(), nullable=True),
        sa.Column("urgencia", sa.String(length=20), nullable=True),
        sa.Column("motivo_busca", sa.String(length=120), nullable=True),
        sa.Column("perfil", sa.String(length=30), nullable=True),
        sa.Column("canal_origem", sa.String(length=30), nullable=True),
        sa.Column("amenidades_desejadas", sa.Text(), nullable=True),
        sa.Column("score", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("perfil_narrativo", sa.Text(), nullable=True),
        sa.Column("resumo", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "intencao IN ('compra','aluguel','investimento')", name="check_intencao"),
        sa.CheckConstraint(
            "status IN ('novo','em_qualificacao','qualificado','agendado','inativo')",
            name="check_status"),
        sa.CheckConstraint(
            "urgencia IN ('baixa','media','alta')", name="check_urgencia"),
        sa.CheckConstraint("orcamento_max >= 0", name="check_orcamento_max"),
        sa.CheckConstraint("orcamento_min >= 0", name="check_orcamento_min"),
        sa.CheckConstraint("quartos >= 0", name="check_quartos"),
        sa.CheckConstraint("score >= 0 AND score <= 10", name="check_score"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agendamentos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("data_hora", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pendente','confirmado','cancelado','realizado')",
            name="check_status_agendamento"),
        sa.CheckConstraint(
            "tipo IN ('visita','reuniao')", name="check_tipo_agendamento"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_agendamentos_ativo_por_lead", "agendamentos", ["lead_id"],
        unique=True, postgresql_where=sa.text(COMPROMISSO_ATIVO),
    )

    op.create_table(
        "lead_channel_identities",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("external_user_id", sa.String(length=100), nullable=True),
        sa.Column("external_chat_id", sa.String(length=100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("conversation_turn", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("tokens_input", sa.Integer(), nullable=False),
        sa.Column("tokens_output", sa.Integer(), nullable=False),
        sa.Column("tokens_total", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="ok", nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("tokens_input >= 0", name="check_tokens_input"),
        sa.CheckConstraint("tokens_output >= 0", name="check_tokens_output"),
        sa.CheckConstraint("tokens_total >= 0", name="check_tokens_total"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "mensagens",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("channel_identity_id", sa.BigInteger(), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_message_id", sa.String(length=100), nullable=True),
        sa.Column("in_reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "timestamp", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "message_type IN ('chat','followup','system_notice','handover')",
            name="check_message_type"),
        sa.CheckConstraint(
            "role IN ('user','assistant','system','tool')", name="check_role"),
        sa.CheckConstraint(
            "status IN ('created','received','generated','sent','failed')",
            name="check_msg_status"),
        sa.ForeignKeyConstraint(["in_reply_to_message_id"], ["mensagens.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "followup_attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("regua", sa.String(length=30), nullable=False),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.String(length=120), nullable=True),
        sa.Column("scheduled_for", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "executed_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "regua IN ('lead_novo_sem_resposta','qualificacao_interrompida',"
            "'pos_envio_imoveis','pos_agendamento')",
            name="check_regua"),
        sa.CheckConstraint(
            "status IN ('generated','sent','failed','skipped')",
            name="check_followup_status"),
        sa.CheckConstraint("attempt_number >= 1", name="check_attempt_number"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["mensagens.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_id", "regua", "attempt_number",
            name="uq_followup_lead_regua_attempt"),
    )

    _criar_role_de_busca()


def _criar_role_de_busca() -> None:
    """A role somente-leitura que executa o SQL escrito pelo agente de busca.

    Esse agente escreve consultas sozinho, e este banco guarda tambem leads,
    telefones e o historico das conversas. Sem uma fronteira no proprio banco,
    uma instrucao escondida numa mensagem de lead tem caminho ate
    `SELECT telefone FROM leads`. E a unica camada de contencao que nao depende
    de o nosso codigo estar certo.

    Duas particularidades do PostgreSQL moldam o que vem abaixo:

    1. role e objeto do CLUSTER, nao do banco. A suite recria o banco `_test` a
       cada sessao e reaplica as migrations, entao na segunda execucao a role ja
       existe — dai o ALTER em vez do CREATE quando ela e encontrada;
    2. os GRANTs, ao contrario, sao por banco. Rodam nos dois, cada um no seu.

    A senha vem de `DB_PASSWORD_BUSCA`, nunca deste arquivo, e e escapada pelo
    proprio servidor com `quote_literal`. Criar role exige superusuario ou
    CREATEROLE; no compose, `sdr` e o usuario de bootstrap e ja tem isso.
    """
    conn = op.get_bind()

    senha = os.getenv("DB_PASSWORD_BUSCA") or SENHA_PADRAO
    senha_sql = conn.execute(
        sa.text("SELECT quote_literal(:s)"), {"s": senha}
    ).scalar()

    ja_existe = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
    ).scalar()
    verbo = "ALTER" if ja_existe else "CREATE"
    conn.execute(sa.text(f"{verbo} ROLE {ROLE} LOGIN PASSWORD {senha_sql}"))

    # `current_database()` nao pode ir num GRANT direto, e o nome do banco muda
    # entre desenvolvimento e teste.
    conn.execute(sa.text(
        "DO $$ BEGIN EXECUTE format("
        f"'GRANT CONNECT ON DATABASE %I TO {ROLE}', current_database()"
        "); END $$;"
    ))
    conn.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
    conn.execute(sa.text(f"GRANT SELECT ON TABLE imoveis TO {ROLE}"))

    # Nenhum GRANT nas demais tabelas, de proposito. Um papel novo no PostgreSQL
    # nasce sem privilegio de tabela nenhum, entao o silencio aqui ja e a
    # negacao — e `tests/test_consulta_catalogo.py` verifica isso contra o
    # banco, em vez de confiar no que este comentario afirma.


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(f"REVOKE SELECT ON TABLE imoveis FROM {ROLE}"))
    conn.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}"))
    conn.execute(sa.text(
        "DO $$ BEGIN EXECUTE format("
        f"'REVOKE CONNECT ON DATABASE %I FROM {ROLE}', current_database()"
        "); END $$;"
    ))
    # A role em si nao e removida: ela e do cluster, e com outro banco ainda
    # concedendo privilegios a ela o DROP falharia.

    op.drop_table("followup_attempts")
    op.drop_table("mensagens")
    op.drop_table("llm_usage")
    op.drop_table("lead_channel_identities")
    op.drop_index("uq_agendamentos_ativo_por_lead", table_name="agendamentos")
    op.drop_table("agendamentos")
    op.drop_table("leads")
    op.drop_index(
        "ix_imoveis_search_vector", table_name="imoveis", postgresql_using="gin")
    op.drop_table("imoveis")
