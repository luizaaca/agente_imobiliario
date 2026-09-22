"""Contenção do SQL que o agente de busca escreve.

Os testes estão em duas camadas, como a própria contenção.

Os primeiros exercitam o validador: o que ele recusa, o que ele deixa passar e
o que ele ajusta. São rápidos e cobrem o caso do modelo errando a sintaxe.

Os últimos vão ao banco com a role `busca_ro` e tentam, de verdade, ler a
tabela de leads e escrever no catálogo — sem passar pelo validador. São eles
que provam a fronteira: se alguém afrouxar o validador amanhã, o dado continua
fora de alcance, e é isso que precisa continuar verdadeiro.
"""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.db.session import conexao_de_busca
from src.services.consulta_catalogo import (
    LIMITE_MAXIMO,
    TAMANHO_MAXIMO,
    ConsultaRecusada,
    executar,
    validar,
)

# SQLSTATE do PostgreSQL para privilégio insuficiente. Comparar o código, e não
# a mensagem, porque a mensagem muda com o `lc_messages` do servidor.
PRIVILEGIO_INSUFICIENTE = "42501"


# --- O que o validador recusa ------------------------------------------------

@pytest.mark.parametrize(
    "sql, esperado_na_recusa",
    [
        ("UPDATE imoveis SET preco = 1", "SELECT"),
        ("DELETE FROM imoveis", "SELECT"),
        ("DROP TABLE imoveis", "SELECT"),
        ("SELECT 1; DROP TABLE leads", "Só um comando"),
        ("SELECT id FROM imoveis -- e o resto", "Comentários"),
        ("SELECT id /* nada */ FROM imoveis", "Comentários"),
        ("SELECT telefone FROM leads", "leads"),
        ("SELECT id FROM imoveis JOIN leads ON true", "leads"),
        ("SELECT id FROM public.mensagens", "mensagens"),
        ("SELECT * FROM pg_user", "pg_"),
        ("SELECT table_name FROM information_schema.tables", "information_schema"),
        ("SELECT id FROM imoveis WHERE id = $1", "$"),
        ("SELECT id FROM imoveis WHERE titulo = 'aberta", "aspa simples"),
        ("", "vazia"),
    ],
)
def test_consulta_recusada(sql, esperado_na_recusa):
    with pytest.raises(ConsultaRecusada) as erro:
        validar(sql)
    assert esperado_na_recusa in str(erro.value)


def test_consulta_longa_demais_e_recusada():
    """O teto é para o payload absurdo, não para a consulta de verdade."""
    sql = "SELECT " + ", ".join(["titulo"] * 2000) + " FROM imoveis"
    assert len(sql) > TAMANHO_MAXIMO
    with pytest.raises(ConsultaRecusada, match="limite"):
        validar(sql)


def test_recusa_da_guarda_e_registrada_com_o_statement(caplog):
    """Uma recusa isolada é engano; repetida, é o que se quer enxergar.

    Sem o statement no log não há como distinguir as duas depois.
    """
    with caplog.at_level(logging.WARNING, logger="src.services.consulta_catalogo"):
        with pytest.raises(ConsultaRecusada):
            executar("SELECT telefone FROM leads")

    registro = "\n".join(caplog.messages)
    assert "status=recusada" in registro
    assert "SELECT telefone FROM leads" in registro


# --- O que o validador não pode recusar --------------------------------------

def test_texto_em_portugues_dentro_de_aspas_nao_e_sintaxe():
    """`do`, `into` e `set` são comandos proibidos e palavras comuns.

    Sem mascarar o conteúdo das aspas, procurar "casa do campo" no catálogo
    seria recusado pela palavra `do` — e o agente não teria como entender por
    quê, já que a consulta dele está correta.
    """
    sql = "SELECT id FROM imoveis WHERE titulo ILIKE '%casa do campo%'"
    preparado, _ = validar(sql)
    assert preparado.startswith(sql)


def test_palavra_proibida_colada_em_outra_nao_dispara():
    """`offset` contém `set`, e `pedido` contém `do`."""
    sql = "SELECT id FROM imoveis ORDER BY preco OFFSET 5 LIMIT 10"
    preparado, avisos = validar(sql)
    assert preparado == sql
    assert avisos == []


def test_from_de_funcao_nao_e_tabela():
    """`EXTRACT(YEAR FROM created_at)` usa FROM sem citar tabela nenhuma."""
    sql = "SELECT EXTRACT(YEAR FROM created_at) FROM imoveis"
    preparado, _ = validar(sql)
    assert preparado.startswith(sql)


def test_with_e_aceito():
    sql = "WITH baratos AS (SELECT * FROM imoveis) SELECT id FROM baratos"
    # `baratos` não é `imoveis`: a CTE é recusada pela conferência de tabela,
    # e a recusa diz qual nome não existe — o agente reescreve sem CTE.
    with pytest.raises(ConsultaRecusada, match="baratos"):
        validar(sql)


# --- O LIMIT -----------------------------------------------------------------

def test_limite_e_acrescentado_quando_falta():
    preparado, avisos = validar("SELECT id FROM imoveis")
    assert preparado == f"SELECT id FROM imoveis LIMIT {LIMITE_MAXIMO}"
    assert avisos == []


def test_limite_dentro_do_teto_e_preservado():
    preparado, avisos = validar("SELECT id FROM imoveis LIMIT 5")
    assert preparado == "SELECT id FROM imoveis LIMIT 5"
    assert avisos == []


def test_limite_acima_do_teto_e_rebaixado_com_aviso():
    """Rebaixar, e não recusar: `LIMIT 500` é o agente querendo ver muito.

    Recusar custaria uma ida ao provider só para ele reescrever o número. O
    aviso volta junto do resultado para ele saber que a lista veio cortada.
    """
    preparado, avisos = validar("SELECT id FROM imoveis LIMIT 500")
    assert preparado == f"SELECT id FROM imoveis LIMIT {LIMITE_MAXIMO}"
    assert avisos == [f"LIMIT reduzido de 500 para {LIMITE_MAXIMO}."]


def test_limite_com_offset_no_fim_nao_duplica():
    """Dois LIMIT na mesma consulta é erro de sintaxe, não teto aplicado."""
    preparado, _ = validar("SELECT id FROM imoveis LIMIT 5 OFFSET 10")
    assert preparado.lower().count("limit") == 1


def test_ponto_e_virgula_no_fim_e_so_pontuacao():
    preparado, _ = validar("SELECT id FROM imoveis LIMIT 3;")
    assert preparado == "SELECT id FROM imoveis LIMIT 3"


# --- Execução de verdade -----------------------------------------------------

def test_consulta_valida_devolve_linhas(catalogo):
    resultado = executar(
        "SELECT titulo, preco FROM imoveis WHERE operacao = 'venda' "
        "ORDER BY preco LIMIT 3"
    )
    assert resultado.colunas == ["titulo", "preco"]
    assert len(resultado.linhas) == 3
    assert "Apartamento Bela Vista Compacto" in resultado.para_texto()


def test_erro_do_postgres_volta_como_texto(catalogo):
    """Coluna inexistente é erro de modelo, e ele se corrige na retentativa."""
    with pytest.raises(ConsultaRecusada) as erro:
        executar("SELECT coluna_que_nao_existe FROM imoveis")
    assert erro.value.motivo == "sql"
    assert "coluna_que_nao_existe" in str(erro.value)


def test_texto_do_resultado_traz_aviso_e_contagem(catalogo):
    resultado = executar("SELECT titulo FROM imoveis LIMIT 500")
    linhas = resultado.para_texto().splitlines()
    assert linhas[0].startswith("LIMIT reduzido")
    assert linhas[1] == "7 linha(s)."
    assert linhas[2] == "titulo"


# --- A fronteira de verdade: a role, sem passar pelo validador ---------------

def test_a_role_nao_le_a_tabela_de_leads():
    """O validador poderia ser afrouxado amanhã; isto não muda por causa disso.

    É a permissão no PostgreSQL que impede o dado de sair, e é ela que este
    teste exercita — a consulta vai direto à conexão, sem validação nenhuma.
    """
    with pytest.raises(SQLAlchemyError) as erro:
        with conexao_de_busca() as conn:
            conn.execute(text("SELECT telefone FROM leads"))
    assert erro.value.orig.sqlstate == PRIVILEGIO_INSUFICIENTE


@pytest.mark.parametrize(
    "tabela", ["leads", "mensagens", "agendamentos", "llm_usage"]
)
def test_a_role_nao_le_nenhuma_tabela_fora_do_catalogo(tabela):
    with pytest.raises(SQLAlchemyError) as erro:
        with conexao_de_busca() as conn:
            conn.execute(text(f"SELECT * FROM {tabela}"))
    assert erro.value.orig.sqlstate == PRIVILEGIO_INSUFICIENTE


def test_a_role_nao_escreve_no_catalogo(catalogo):
    """Ler `imoveis` é o que ela pode; mudar, não."""
    with pytest.raises(SQLAlchemyError):
        with conexao_de_busca() as conn:
            conn.execute(text("UPDATE imoveis SET preco = 1"))


def test_a_transacao_e_somente_leitura_e_tem_tempo_limite():
    with conexao_de_busca() as conn:
        somente_leitura = conn.execute(text("SHOW transaction_read_only")).scalar()
        limite = conn.execute(text("SHOW statement_timeout")).scalar()
    assert somente_leitura == "on"
    assert limite == "3s"
