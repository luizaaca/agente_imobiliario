"""Configuração da suíte de testes.

Os testes rodam contra um PostgreSQL de verdade, num banco separado
(`<banco>_test`), e não contra SQLite. O motivo é concreto: SQLite ignora o
tamanho declarado em VARCHAR, então um bug real como gravar 95 caracteres em
uma coluna VARCHAR(30) passaria despercebido. As CHECK constraints e o
comportamento transacional também só são fiéis no Postgres.

A URL do banco é trocada ANTES de qualquer import de `src`, porque
`src/db/session.py` cria a engine no momento do import.
"""

import os
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()


def _url_de_teste(url: str) -> str:
    """Deriva a URL do banco de teste a partir da URL de desenvolvimento."""
    partes = urlparse(url)
    nome = partes.path.lstrip("/") or "agente_sdr"
    return urlunparse(partes._replace(path=f"/{nome}_test"))


_URL_DEV = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://sdr:sdr_dev_pass@127.0.0.1:5432/agente_sdr"
)
DATABASE_URL_TESTE = _url_de_teste(_URL_DEV)

# Precisa vir antes dos imports de src.
os.environ["DATABASE_URL"] = DATABASE_URL_TESTE
# Sobrescrito, não `setdefault`: o .env do desenvolvedor já populou o ambiente
# e vazaria provider e modelo reais para dentro da suíte. A chave é fictícia de
# propósito — nenhum teste deve alcançar um provider de verdade.
os.environ["OPENAI_API_KEY"] = "sk-teste"
os.environ["OPENAI_BASE_URL"] = ""
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_MODEL"] = "modelo-de-teste"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from src.db.models import Base, Imovel  # noqa: E402
from src.db.session import engine, get_db  # noqa: E402


def _recriar_banco_de_teste() -> None:
    """Recria o banco de teste do zero.

    Derrubar e criar de novo a cada sessão é o que permite aplicar as
    migrations em um banco limpo; sem isso, `alembic upgrade head` esbarraria
    nas tabelas da execução anterior.
    """
    partes = urlparse(DATABASE_URL_TESTE)
    nome_teste = partes.path.lstrip("/")
    admin_url = urlunparse(
        partes._replace(scheme="postgresql", path="/postgres")
    )

    with psycopg.connect(admin_url, autocommit=True, connect_timeout=10) as conn:
        conn.execute(
            f'DROP DATABASE IF EXISTS "{nome_teste}" WITH (FORCE)'
        )
        conn.execute(f'CREATE DATABASE "{nome_teste}"')


@pytest.fixture(scope="session", autouse=True)
def banco_de_teste():
    """Prepara o schema do banco de teste uma vez por sessão.

    O schema vem das migrations, e não de `Base.metadata.create_all()`: é o
    mesmo caminho que roda em produção, então um modelo que andou sem a
    migration correspondente quebra a suíte em vez de passar despercebido.
    """
    try:
        _recriar_banco_de_teste()
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL indisponível para os testes: {e}")

    # Config sem arquivo: o alembic.ini só traz script_location e a seção de
    # logging, e deixar essa seção de fora evita que o alembic reconfigure o
    # logging do processo e engula a saída do pytest.
    config = Config()
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head")

    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def banco_limpo(banco_de_teste):
    """Zera as tabelas antes de cada teste, garantindo isolamento.

    Necessário porque os services abrem sessões próprias via `get_db()`: um
    rollback na sessão do teste não desfaria o que eles commitaram.
    """
    tabelas = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tabelas} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db():
    """Sessão de banco para uso direto no teste."""
    with get_db() as sessao:
        yield sessao


# --- Catálogo de apoio -------------------------------------------------------

# A zona segue o formato real da coluna no catalogo ('zona_oeste', com
# underscore): e disso que depende o teste de quem escreve "zona oeste".
IMOVEIS_DE_TESTE = [
    # titulo, tipo, operacao, bairro, zona, preco, quartos, area, tags
    ("Apartamento Bela Vista Compacto", "apartamento", "venda", "Bela Vista", "centro", 510000, 2, 55, "metro, reformado"),
    ("Apartamento Bela Vista Vista Livre", "apartamento", "venda", "Bela Vista", "centro", 610000, 2, 62, "varanda gourmet"),
    ("Cobertura Moema Alto Padrao", "cobertura", "venda", "Moema", "zona_sul", 1800000, 3, 180, "piscina, varanda gourmet"),
    ("Studio Pinheiros Investidor", "studio", "venda", "Pinheiros", "zona_oeste", 420000, 1, 28, "investidor, metro"),
    ("Apartamento Tatuape Aluguel", "apartamento", "aluguel", "Tatuape", "zona_leste", 3200, 2, 60, "metro"),
    ("Sala Comercial Paulista", "sala_comercial", "aluguel", "Bela Vista", "centro", 4500, 0, 40, "corporativo"),
]


@pytest.fixture
def catalogo(db):
    """Insere um catálogo pequeno e previsível para os testes de busca."""
    for i, (titulo, tipo, operacao, bairro, zona, preco, quartos, area, tags) in enumerate(
        IMOVEIS_DE_TESTE, start=1
    ):
        db.add(
            Imovel(
                id=i,
                titulo=titulo,
                tipo=tipo,
                finalidade="comercial" if tipo == "sala_comercial" else "residencial",
                operacao=operacao,
                bairro=bairro,
                zona=zona,
                cidade="Sao Paulo",
                estado="SP",
                preco=preco,
                quartos=quartos,
                area_m2=area,
                descricao=f"Descricao de {titulo}",
                tags=tags,
                disponivel=True,
            )
        )
    db.commit()
    return IMOVEIS_DE_TESTE


# --- LLM simulado ------------------------------------------------------------


def modelo_fake(*respostas):
    """Cria um FunctionModel que devolve as respostas na ordem informada.

    Cada resposta é um texto (`str`) ou uma tool call `(nome, argumentos)`.
    A última resposta se repete caso o agente peça mais turnos.
    """
    passo = {"n": 0}

    def responder(messages, info):
        indice = min(passo["n"], len(respostas) - 1)
        passo["n"] += 1
        resposta = respostas[indice]

        if isinstance(resposta, tuple):
            nome, argumentos = resposta
            return ModelResponse(parts=[ToolCallPart(tool_name=nome, args=argumentos)])
        return ModelResponse(parts=[TextPart(content=resposta)])

    return FunctionModel(responder)


@pytest.fixture
def llm_fake():
    """Fábrica de modelos simulados, para injetar via `agent.override`."""
    return modelo_fake
