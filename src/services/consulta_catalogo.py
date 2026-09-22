"""Execução do SQL que o agente de busca escreve.

É o único código do sistema que ninguém revisou antes de rodar. O banco é o
mesmo que guarda leads, telefones e o histórico das conversas, e o contexto do
agente de busca inclui o perfil narrativo — texto derivado do que o lead
digitou. Uma instrução escondida numa mensagem de lead chega até aqui.

A fronteira de verdade é a role `busca_ro`, que só tem `SELECT` em `imoveis`
(ver a migration `e3c7a94f1b05`). O que este módulo acrescenta é profundidade:
recusa cedo, com uma mensagem que o agente entende, em vez de deixar o
PostgreSQL recusar com um erro de permissão que não ensina nada.

A recusa é sempre em texto: o agente reescreve a consulta e tenta de novo, que
é o comportamento desejado tanto para uma tentativa hostil quanto para um
`ORDER BY` com nome de coluna errado.
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.db.models import Imovel
from src.db.session import conexao_de_busca

logger = logging.getLogger(__name__)

# A única tabela que o agente de busca enxerga.
TABELA_PERMITIDA = "imoveis"

# Teto de linhas por consulta. Ele pode ler dezenas de imóveis e devolver três
# — o limite é do statement, não da resposta —, mas não o catálogo inteiro a
# cada pergunta: 286 linhas são cerca de 13 mil tokens.
LIMITE_MAXIMO = 100

# Um SELECT sobre uma tabela só não chega perto disto. O teto existe para o
# payload absurdo, não para a consulta legítima.
TAMANHO_MAXIMO = 4000

# Comandos que não têm o que fazer numa busca. `into` entra na lista porque
# `SELECT ... INTO` cria tabela; `do` e `execute` porque são as duas formas de
# rodar SQL dinâmico.
COMANDOS_PROIBIDOS = (
    "insert", "update", "delete", "merge", "truncate", "copy",
    "drop", "alter", "create", "comment", "refresh", "reindex", "vacuum",
    "grant", "revoke", "security",
    "do", "call", "execute", "prepare", "into",
    "set", "reset", "begin", "commit", "rollback", "savepoint", "lock",
    "listen", "notify", "analyze", "explain",
)

# Nomes que só aparecem em consulta que quer sair do catálogo.
IDENTIFICADORES_PROIBIDOS = (
    "pg_", "information_schema", "current_setting", "dblink",
    "lo_import", "lo_export", "pg_catalog",
)

# Palavras que seguem FROM/JOIN sem serem o nome de uma tabela. As colunas
# entram porque `EXTRACT(YEAR FROM created_at)` e `TRIM(BOTH ' ' FROM titulo)`
# usam a palavra FROM sem que venha tabela nenhuma depois dela.
_NAO_SAO_TABELA = frozenset(
    {"lateral", "only"} | {coluna.name for coluna in Imovel.__table__.columns}
)

_ABERTURAS = ("select", "with")

_DEPOIS_DE_FROM = re.compile(r"\b(?:from|join)\s+([a-z_][\w.\"]*)", re.IGNORECASE)
_LIMITE_NO_FIM = re.compile(r"\blimit\s+(\d+)\s*(?:\boffset\s+\d+\s*)?$", re.IGNORECASE)
_PRIMEIRA_PALAVRA = re.compile(r"^\s*([a-z]+)", re.IGNORECASE)


class ConsultaRecusada(ValueError):
    """Consulta que não roda, com a razão em texto para o agente se corrigir.

    `motivo` separa quem recusou, e serve à observabilidade: `guarda` é uma
    consulta barrada aqui, e merece atenção quando se repete; `sql` é o
    PostgreSQL reclamando de sintaxe ou de coluna inexistente, que é erro
    comum de modelo e se resolve sozinho na retentativa.
    """

    def __init__(self, mensagem: str, motivo: str = "guarda"):
        super().__init__(mensagem)
        self.motivo = motivo


@dataclass
class ResultadoConsulta:
    """Linhas devolvidas, e o que precisou ser ajustado no caminho."""
    colunas: list[str]
    linhas: list[tuple]
    sql_executado: str
    avisos: list[str] = field(default_factory=list)

    def para_texto(self) -> str:
        """As linhas em formato compacto, para caberem no contexto do modelo.

        Separado por `|` e sem alinhamento: uma tabela alinhada gastaria em
        espaços um terço dos tokens, e o modelo lê as duas igualmente bem.
        """
        cabecalho = " | ".join(self.colunas)
        corpo = [
            " | ".join(_celula(valor) for valor in linha) for linha in self.linhas
        ]
        partes = [*self.avisos] if self.avisos else []
        partes.append(f"{len(self.linhas)} linha(s).")
        partes.append(cabecalho)
        partes.extend(corpo)
        return "\n".join(partes)


def _celula(valor) -> str:
    """Um valor de coluna como texto curto."""
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return f"{valor:f}".rstrip("0").rstrip(".") or "0"
    if isinstance(valor, float):
        return f"{valor:g}"
    return str(valor).replace("\n", " ").replace("|", "/")


def _mascarar_literais(sql: str) -> str:
    """Troca o conteúdo das aspas simples por espaços, preservando o tamanho.

    Toda a inspeção acontece sobre esta versão mascarada, para que o texto que
    o agente procura no catálogo não seja confundido com sintaxe. Sem isso,
    `WHERE titulo ILIKE '%casa do campo%'` seria recusada pela palavra `do`, e
    um bairro chamado "Vila Update" derrubaria a consulta.

    O tamanho é preservado para as posições continuarem valendo na string
    original — é assim que o `LIMIT` é reescrito no SQL de verdade, e não na
    cópia.
    """
    saida = list(sql)
    dentro = False
    i = 0
    while i < len(sql):
        if not dentro:
            dentro = sql[i] == "'"
            i += 1
            continue
        if sql[i] == "'":
            # Aspa dobrada é a aspa escapada do SQL: continua dentro.
            if i + 1 < len(sql) and sql[i + 1] == "'":
                saida[i] = saida[i + 1] = " "
                i += 2
                continue
            dentro = False
            i += 1
            continue
        saida[i] = " "
        i += 1

    if dentro:
        raise ConsultaRecusada(
            "Há uma aspa simples aberta e não fechada na consulta."
        )
    return "".join(saida)


def validar(sql: str) -> tuple[str, list[str]]:
    """Devolve o SQL pronto para executar e os avisos do que foi ajustado.

    Levanta `ConsultaRecusada` com a explicação quando não há ajuste possível.
    """
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise ConsultaRecusada("A consulta veio vazia.")
    if len(sql) > TAMANHO_MAXIMO:
        raise ConsultaRecusada(
            f"A consulta tem {len(sql)} caracteres e o limite é "
            f"{TAMANHO_MAXIMO}. Peça menos colunas ou divida em duas."
        )

    mascarado = _mascarar_literais(sql)

    if ";" in mascarado:
        raise ConsultaRecusada(
            "Só um comando por consulta. Tire o ';' do meio e mande um "
            "`SELECT` de cada vez."
        )
    if "--" in mascarado or "/*" in mascarado:
        raise ConsultaRecusada(
            "Comentários não são aceitos na consulta. Mande só o `SELECT`."
        )
    if "$" in mascarado:
        raise ConsultaRecusada(
            "Não use '$': nem parâmetros posicionais, nem aspas de cifrão. "
            "Escreva os valores direto na consulta."
        )

    primeira = _PRIMEIRA_PALAVRA.match(mascarado)
    if not primeira or primeira.group(1).lower() not in _ABERTURAS:
        raise ConsultaRecusada(
            "A consulta precisa começar com `SELECT` ou `WITH`. Esta ferramenta "
            "só lê o catálogo."
        )

    minusculo = mascarado.lower()
    for comando in COMANDOS_PROIBIDOS:
        if re.search(rf"\b{comando}\b", minusculo):
            raise ConsultaRecusada(
                f"'{comando}' não é permitido aqui. Esta ferramenta só executa "
                f"consulta de leitura sobre `{TABELA_PERMITIDA}`."
            )
    for identificador in IDENTIFICADORES_PROIBIDOS:
        if identificador in minusculo:
            raise ConsultaRecusada(
                f"'{identificador}' não é permitido aqui. A única tabela "
                f"disponível é `{TABELA_PERMITIDA}`."
            )

    _conferir_tabelas(mascarado)

    preparado, avisos = _com_limite(sql, mascarado)
    return preparado, avisos + _avisos_da_tsquery(sql)


def _conferir_tabelas(mascarado: str) -> None:
    """Toda tabela citada depois de FROM ou JOIN precisa ser `imoveis`."""
    for bruto in _DEPOIS_DE_FROM.findall(mascarado):
        nome = bruto.replace('"', "").split(".")[-1].lower()
        if nome in _NAO_SAO_TABELA:
            continue
        if nome != TABELA_PERMITIDA:
            raise ConsultaRecusada(
                f"'{nome}' não está disponível. A única tabela que esta "
                f"ferramenta lê é `{TABELA_PERMITIDA}`."
            )


# O argumento de texto de um `*_tsquery`, que é onde a sintaxe de busca web
# vale e a do SQL não.
_ARGUMENTO_DA_TSQUERY = re.compile(
    r"tsquery\s*\(\s*'[^']*'\s*,\s*'([^']*)'", re.IGNORECASE
)
_OPERADOR_QUE_NAO_E = re.compile(r"\b(and|not)\b", re.IGNORECASE)
_TERMO_COM_UNDERSCORE = re.compile(r"\b\w+_\w+\b")


_PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]{4,}")

# Para dobrar acento sem depender da extensão `unaccent`, que não está
# instalada no cluster. Só minúsculas: os lexemas do `ts_stat` já vêm assim.
_COM_ACENTO = "áàâãäéèêëíìîïóòôõöúùûüçñ"
_SEM_ACENTO = "aaaaaeeeeiiiiooooouuuucn"

# Um lexema precisa aparecer neste tanto de anúncios para valer como
# vocabulário do catálogo. Abaixo disso é palavra de um anúncio só, e avisar
# sobre ela seria ruído.
MINIMO_DE_ANUNCIOS = 10

# Lexemas dobrados mais curtos que isto são prefixo de palavra demais: `vã`
# vira `va` e acusaria `vaga`; `pé` vira `pe` e acusaria `perto`.
MINIMO_DE_LETRAS = 4

# Quanto a palavra escrita pode exceder o lexema dobrado. O radicalizador corta
# a terminação, então `estacao`, contra o lexema `estaçã` dobrado em `estaca`,
# sobra uma letra. Três letras já é outra palavra: `arejado` não é `área`.
SOBRA_MAXIMA = 2

_vocabulario: dict | None = None


def _ler_vocabulario_acentuado(minimo: int = MINIMO_DE_ANUNCIOS) -> dict:
    """As palavras que o catálogo escreve com acento, lidas do próprio índice.

    Devolve `{forma_dobrada: (lexema_acentuado, em_quantos_anúncios)}`. Sai do
    `ts_stat` sobre o `search_vector`, que é exatamente o vocabulário contra o
    qual a consulta do agente vai casar. Uma lista fixa no código envelheceria
    junto com o catálogo, e aqui quem manda é o catálogo.
    """
    consulta = text(
        "SELECT word, ndoc, translate(word, :acentos, :simples) AS dobrada "
        "FROM ts_stat('SELECT search_vector FROM imoveis WHERE disponivel') "
        "WHERE ndoc >= :minimo "
        "  AND word <> translate(word, :acentos, :simples)"
    )
    parametros = {
        "acentos": _COM_ACENTO, "simples": _SEM_ACENTO, "minimo": minimo,
    }
    with conexao_de_busca() as conn:
        linhas = conn.execute(consulta, parametros).fetchall()

    return {
        dobrada: (acentuada, ndoc)
        for acentuada, ndoc, dobrada in linhas
        if len(dobrada) >= MINIMO_DE_LETRAS
    }


def _vocabulario_acentuado() -> dict:
    """O vocabulário acentuado, lido uma vez por processo.

    A falha ao ler também fica no cache. O aviso é apoio e não barreira: tentar
    de novo a cada consulta custaria uma ida ao banco por busca para recuperar
    algo que, sem ele, apenas deixa de ser dito.
    """
    global _vocabulario
    if _vocabulario is None:
        try:
            _vocabulario = _ler_vocabulario_acentuado()
        except SQLAlchemyError as e:
            logger.warning(
                "event=vocabulario_acentuado status=indisponivel erro=%s", e
            )
            _vocabulario = {}
    return _vocabulario


def _avisos_de_vocabulario(argumento: str, vocabulario: dict) -> list[str]:
    """Aponta palavra escrita sem acento que o catálogo escreve com acento.

    Separada da leitura para poder ser exercitada sem banco, e porque a regra é
    o que muda: `metro` e `metrô` são lexemas diferentes, então quem procura a
    forma sem acento não alcança nenhum dos anúncios que usam a outra.
    """
    avisos = []
    for palavra in _PALAVRA.findall(argumento):
        minuscula = palavra.lower()
        for dobrada, (acentuada, ndoc) in vocabulario.items():
            if not minuscula.startswith(dobrada):
                continue
            if len(minuscula) - len(dobrada) <= SOBRA_MAXIMA:
                avisos.append(
                    f"Atenção: '{palavra}' não alcança o lexema '{acentuada}', "
                    f"que está em {ndoc} anúncios — sem o acento o PostgreSQL "
                    f"gera outro lexema. Se era essa a palavra, escreva-a "
                    f"acentuada."
                )
                break
    return avisos


def _avisos_da_tsquery(sql: str) -> list[str]:
    """Aponta o que, dentro de uma tsquery, não faz o que parece fazer.

    Três enganos observados em consultas reais, os três silenciosos — a
    consulta roda, devolve menos do que devia ou nada, e ninguém fica sabendo
    por quê. Vale mais como aviso que como recusa: a consulta pode estar
    correta para outra intenção, e quem decide é quem a escreveu.
    """
    argumentos = _ARGUMENTO_DA_TSQUERY.findall(sql)
    if not argumentos:
        return []

    # Lido aqui e não no topo de `validar` para que a consulta sem busca
    # textual nunca pague a ida ao banco.
    vocabulario = _vocabulario_acentuado()

    avisos: list[str] = []
    for argumento in argumentos:
        avisos.extend(_avisos_de_vocabulario(argumento, vocabulario))
        if achado := _OPERADOR_QUE_NAO_E.search(argumento):
            palavra = achado.group(1)
            avisos.append(
                f"Atenção: '{palavra}' não é operador de tsquery — virou termo "
                f"de busca, e nenhum anúncio contém essa palavra, então esta "
                f"condição casa zero. O espaço já significa E; para OU use "
                f"`or`, para NÃO use `-` colado na palavra."
            )
        for termo in _TERMO_COM_UNDERSCORE.findall(argumento):
            avisos.append(
                f"Atenção: '{termo}' dentro da tsquery vira adjacência "
                f"('{termo.replace('_', ' <-> ')}'), que exige as palavras "
                f"coladas e restringe muito. Use a palavra simples aqui, ou "
                f"`tags ILIKE '%{termo}%'` para casar a tag literal."
            )
    return list(dict.fromkeys(avisos))


def _com_limite(sql: str, mascarado: str) -> tuple[str, list[str]]:
    """Garante um `LIMIT` no fim, dentro do teto.

    Rebaixar é melhor que recusar: um `LIMIT 500` é o agente querendo ver o
    catálogo, não uma tentativa de burlar nada, e recusar custaria uma ida ao
    provider para ele reescrever o número. O aviso vai junto do resultado, para
    ele saber que a lista veio cortada.
    """
    achado = _LIMITE_NO_FIM.search(mascarado)
    if achado is None:
        return f"{sql} LIMIT {LIMITE_MAXIMO}", []

    pedido = int(achado.group(1))
    if pedido <= LIMITE_MAXIMO:
        return sql, []

    inicio, fim = achado.span(1)
    return (
        sql[:inicio] + str(LIMITE_MAXIMO) + sql[fim:],
        [f"LIMIT reduzido de {pedido} para {LIMITE_MAXIMO}."],
    )


def executar(sql: str, correlation_id: str | None = None) -> ResultadoConsulta:
    """Valida e executa a consulta, devolvendo as linhas.

    `ConsultaRecusada` cobre os dois jeitos de a consulta não rodar — barrada
    aqui, ou recusada pelo PostgreSQL —, porque para quem chamou a ação é a
    mesma: devolver a explicação ao agente e deixá-lo reescrever.
    """
    try:
        preparado, avisos = validar(sql)
    except ConsultaRecusada as e:
        # A consulta recusada vai inteira para o log. Uma recusa isolada é o
        # modelo errando; a mesma recusa se repetindo é o que se quer enxergar,
        # e sem o statement não há como distinguir uma da outra depois.
        logger.warning(
            "event=consulta_do_catalogo status=recusada correlation_id=%s "
            "razao=%s sql=%r",
            correlation_id, e, (sql or "")[:TAMANHO_MAXIMO],
        )
        raise

    try:
        with conexao_de_busca() as conn:
            cursor = conn.execute(text(preparado))
            colunas = list(cursor.keys())
            linhas = [tuple(linha) for linha in cursor.fetchall()]
    except SQLAlchemyError as e:
        # `orig` é a exceção do psycopg, com a mensagem do servidor; o str() do
        # wrapper do SQLAlchemy traz a consulta inteira junto, e ela voltaria
        # duplicada para dentro do contexto do modelo.
        detalhe = str(getattr(e, "orig", e)).strip().splitlines()[0]
        logger.warning(
            "event=consulta_do_catalogo status=erro_sql correlation_id=%s "
            "tipo_erro=%s detalhe=%s",
            correlation_id, type(e).__name__, detalhe,
        )
        raise ConsultaRecusada(
            f"O PostgreSQL recusou a consulta: {detalhe}", motivo="sql"
        ) from e

    logger.info(
        "event=consulta_do_catalogo status=ok correlation_id=%s linhas=%s "
        "avisos=%s",
        correlation_id, len(linhas), len(avisos),
    )
    return ResultadoConsulta(
        colunas=colunas, linhas=linhas, sql_executado=preparado, avisos=avisos
    )
