"""role somente-leitura para o SQL escrito pelo agente de busca

Revision ID: e3c7a94f1b05
Revises: c8f1d3a52b07
Create Date: 2026-09-22

O agente de busca consulta o catalogo por SQL que ele mesmo escreve. Este banco
guarda tambem leads, telefones e o historico das conversas, e o contexto desse
agente inclui o perfil narrativo -- texto derivado do que o lead digitou. Sem
uma fronteira no proprio banco, uma instrucao escondida numa mensagem de lead
tem caminho ate `SELECT telefone FROM leads`.

A role recebe SELECT em `imoveis` e nada mais. E a unica das quatro camadas de
contencao que nao depende de o nosso codigo estar certo.

Duas particularidades do PostgreSQL moldam esta migration:

1. role e objeto do CLUSTER, nao do banco. A suite de testes recria o banco
   `_test` a cada sessao e reaplica as migrations, entao na segunda execucao a
   role ja existe -- dai o ALTER em vez do CREATE quando ela e encontrada.
2. os GRANTs, ao contrario, sao por banco. Rodam nos dois, cada um no seu.

A senha vem de `DB_PASSWORD_BUSCA`, nunca deste arquivo, e e escapada pelo
proprio servidor com `quote_literal`.

Criar role exige superusuario ou CREATEROLE. No compose, `sdr` e o usuario de
bootstrap do cluster e ja tem isso.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c7a94f1b05"
down_revision: str | None = "c8f1d3a52b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Escrita literalmente, e nao importada de `src.config`, para esta migration
# continuar reproduzindo este estado historico mesmo que a configuracao mude.
ROLE = "busca_ro"
SENHA_PADRAO = "busca_ro_dev_pass"


def upgrade() -> None:
    conn = op.get_bind()

    senha = os.getenv("DB_PASSWORD_BUSCA") or SENHA_PADRAO
    # O escape e do servidor: uma senha com aspa simples quebraria o comando se
    # fosse interpolada crua, e `CREATE ROLE` nao aceita bind parameter.
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

    # Nenhum GRANT nas demais tabelas, de proposito. Um papel novo no
    # PostgreSQL nasce sem privilegio de tabela nenhum, entao o silencio aqui
    # ja e a negacao -- e `tests/test_consulta_catalogo.py` verifica isso
    # contra o banco, em vez de confiar no que este comentario afirma.


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(f"REVOKE SELECT ON TABLE imoveis FROM {ROLE}"))
    conn.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}"))
    conn.execute(sa.text(
        "DO $$ BEGIN EXECUTE format("
        f"'REVOKE CONNECT ON DATABASE %I FROM {ROLE}', current_database()"
        "); END $$;"
    ))

    # A role em si nao e removida. Ela e do cluster: com o banco de teste ainda
    # concedendo privilegios a ela, o DROP falharia -- e derrubar uma role que
    # outro banco usa e pior que deixar uma role sem privilegio nenhum, que e
    # no que ela fica depois dos REVOKEs acima.
