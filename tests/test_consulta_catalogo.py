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

from src.db.models import Imovel
from src.db.session import conexao_de_busca
from src.services import consulta_catalogo
from src.services.consulta_catalogo import (
    LIMITE_MAXIMO,
    TAMANHO_MAXIMO,
    ConsultaRecusada,
    _avisos_de_vocabulario,
    _ler_vocabulario_acentuado,
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


# --- A sintaxe da tsquery, que não é a do SQL --------------------------------

def test_and_dentro_da_tsquery_e_avisado():
    """`and` não é operador ali: vira termo, e nenhum anúncio o contém.

    Medido no catálogo: `websearch_to_tsquery('portuguese','varanda gourmet
    and metro')` produz `'varand' & 'gourmet' & 'and' & 'metr'` e casa zero,
    sempre. A consulta roda, não dá erro, e devolve nada — o tipo de engano que
    ninguém descobre olhando o resultado.
    """
    _, avisos = validar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        "websearch_to_tsquery('portuguese', 'varanda gourmet and metro')"
    )

    assert any("'and' não é operador" in a for a in avisos)
    assert any("casa zero" in a for a in avisos)


def test_not_dentro_da_tsquery_tambem_e_avisado():
    _, avisos = validar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        "websearch_to_tsquery('portuguese', 'casa not garagem')"
    )
    assert any("'not' não é operador" in a for a in avisos)


def test_nome_de_tag_dentro_da_tsquery_e_avisado():
    """O underscore vira adjacência e restringe muito mais do que parece.

    `metro_proximo` casa 36 imóveis; `metro` casa 96. A diferença é todo
    anúncio que fala de metrô sem usar as duas palavras coladas nessa ordem.
    """
    _, avisos = validar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        "websearch_to_tsquery('portuguese', 'metro_proximo')"
    )

    aviso = next(a for a in avisos if "metro_proximo" in a)
    assert "metro <-> proximo" in aviso
    assert "tags ILIKE" in aviso


def test_a_tsquery_bem_escrita_nao_gera_aviso():
    """Frase entre aspas e espaço como E: a forma correta fica calada."""
    _, avisos = validar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        'websearch_to_tsquery(\'portuguese\', \'"varanda gourmet" metro\')'
    )
    assert avisos == []


def test_underscore_fora_da_tsquery_nao_gera_aviso():
    """`tags ILIKE '%metro_proximo%'` é exatamente o jeito certo de usar a tag."""
    _, avisos = validar(
        "SELECT id FROM imoveis WHERE tags ILIKE '%metro_proximo%' "
        "AND zona = 'zona_sul'"
    )
    assert avisos == []


def test_o_aviso_chega_ao_agente_no_texto_do_resultado(catalogo):
    """Aviso que não volta com as linhas não corrige nada."""
    resultado = executar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        "websearch_to_tsquery('portuguese', 'varanda and metro')"
    )
    assert "não é operador" in resultado.para_texto().splitlines()[0]


# --- O vocabulário do catálogo, contra a palavra sem acento ------------------

# Como o catálogo de verdade devolve: lexema dobrado, lexema real, anúncios.
VOCABULARIO = {
    "metro": ("metrô", 63),
    "condomini": ("condomíni", 120),
    "proxim": ("próxim", 97),
    "edifici": ("edifíci", 73),
    "sala": ("salã", 40),
}


@pytest.mark.parametrize(
    "argumento, esperado_no_aviso",
    [
        ("metro", "metrô"),
        ("metro or bairro", "metrô"),
        ("condominio fechado", "condomíni"),
        ("proximo ao parque", "próxim"),
    ],
)
def test_palavra_sem_acento_e_avisada(argumento, esperado_no_aviso):
    """`metro` e `metrô` são lexemas diferentes: um não alcança o outro.

    Medido no catálogo: 63 anúncios escrevem `metrô`, e nenhum deles responde a
    `metro`. O engano é silencioso — a consulta roda e devolve outra coisa.
    """
    avisos = _avisos_de_vocabulario(argumento, VOCABULARIO)

    assert len(avisos) == 1
    assert esperado_no_aviso in avisos[0]


@pytest.mark.parametrize(
    "argumento",
    [
        "metrô or estação",        # já escrito com acento
        "varanda gourmet",         # não está no vocabulário acentuado
        "churrasqueira",
        "vaga coberta",            # `vã` dobra em `va`: curto demais para acusar
        "arejado",                 # `áre` dobra em `are`: idem
        "metropolitano",           # sobra de mais: é outra palavra
        "metropole",               # quatro letras de sobra já é outra palavra
        "aproxima",                # o lexema no meio da palavra é coincidência
    ],
)
def test_palavra_fora_do_alcance_nao_e_avisada(argumento):
    """Aviso que aparece à toa é aviso que o agente aprende a ignorar."""
    assert _avisos_de_vocabulario(argumento, VOCABULARIO) == []


def test_o_aviso_informa_sem_mandar():
    """`sala` casa o lexema de *salão*, que é outra palavra e não um acento.

    A regra não distingue os dois casos, então a redação precisa deixar a
    decisão com quem escreveu a consulta.
    """
    aviso = _avisos_de_vocabulario("sala ampla", VOCABULARIO)[0]

    assert "Se era essa a palavra" in aviso


def test_o_aviso_de_vocabulario_chega_pela_validacao(monkeypatch):
    """A regra pode estar certa e não estar ligada em lugar nenhum."""
    monkeypatch.setattr(
        consulta_catalogo, "_vocabulario_acentuado", lambda: VOCABULARIO
    )
    resultado = validar(
        "SELECT id FROM imoveis WHERE search_vector @@ "
        "websearch_to_tsquery('portuguese', 'metro or bairro')"
    )

    assert any("metrô" in aviso for aviso in resultado[1])


def test_consulta_sem_busca_textual_nao_procura_vocabulario(monkeypatch):
    """Vocabulário custa uma ida ao banco; consulta sem tsquery não paga."""
    def nao_deveria_ser_chamado():
        raise AssertionError("leu o vocabulário sem precisar")

    monkeypatch.setattr(
        consulta_catalogo, "_vocabulario_acentuado", nao_deveria_ser_chamado
    )
    assert validar("SELECT id FROM imoveis WHERE zona = 'zona_sul'")[1] == []


def test_o_mesmo_termo_em_duas_condicoes_avisa_uma_vez():
    """O agente repete a mesma tsquery nas duas pontas de um OR."""
    sql = (
        "SELECT id FROM imoveis WHERE "
        "search_vector @@ websearch_to_tsquery('portuguese', 'metro_proximo') "
        "OR search_vector @@ websearch_to_tsquery('portuguese', 'metro_proximo')"
    )
    assert len(validar(sql)[1]) == 1


def test_o_vocabulario_sai_do_catalogo_e_nao_de_uma_lista_no_codigo(db):
    """Uma lista fixa envelheceria junto com o catálogo.

    O `ts_stat` lê o mesmo índice contra o qual a consulta do agente vai casar,
    então a palavra que entrar no catálogo amanhã já passa a ser conhecida.
    """
    for i in range(3):
        db.add(Imovel(
            id=500 + i, titulo=f"Apartamento com varanda {i}" + (" japonês" * (i == 0)),
            descricao=(
                "Fica ao lado da estação do metrô, em prédio de pé-direito "
                "alto com salão de festas."
            ),
            tipo="apartamento", finalidade="residencial", operacao="venda",
            bairro="Saude", zona="zona_sul", cidade="Sao Paulo", estado="SP",
            preco=500000, area_m2=60, quartos=2, disponivel=True,
        ))
    db.commit()

    vocabulario = _ler_vocabulario_acentuado(minimo=3)

    assert vocabulario["metro"] == ("metrô", 3)
    assert "estaca" in vocabulario
    # `pé` dobra em `pe`, que é prefixo de `perto`, `pequeno`, `pedido`.
    assert "pe" not in vocabulario
    # `japonês` está num anúncio só: é palavra daquele anúncio, não vocabulário.
    assert "japones" not in vocabulario


def test_sem_vocabulario_acentuado_o_aviso_some(db):
    """Catálogo sem palavra acentuada nenhuma não tem do que avisar."""
    assert _ler_vocabulario_acentuado(minimo=1) == {}
