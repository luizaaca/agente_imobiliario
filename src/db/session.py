"""Gerenciamento de sessão do banco de dados."""

from contextlib import contextmanager

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings

_url = settings.database_url_safe

# connect_timeout evita que a aplicação congele indefinidamente quando o banco
# está inacessível (ex.: host resolvendo para um IPv6 sem rota até o container).
_connect_args = {"connect_timeout": 10} if _url.startswith("postgresql") else {}

engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Session:
    """Context manager para sessão de banco de dados."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """Cria e retorna uma nova sessão (caller é responsável por fechar)."""
    return SessionLocal()


# --- Acesso somente-leitura ao catálogo --------------------------------------
#
# Engine separada, com a role `busca_ro`, para executar o SQL que o agente de
# busca escreve. O pool é pequeno de propósito: uma conexão por busca em
# andamento, e buscas não acontecem em paralelo dentro de um turno.
#
# A engine é criada no import, como a principal, mas `create_engine` não abre
# conexão — então a aplicação sobe normalmente mesmo antes de a migration que
# cria a role ter rodado. Quem descobre a ausência é a primeira busca.
engine_busca = create_engine(
    settings.database_url_busca,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=2,
    connect_args=_connect_args,
)

# Teto de tempo de cada consulta do agente de busca. Generoso para o volume da
# POC — a busca mais pesada é um scan sobre índice GIN, na casa do
# milissegundo. Existe para o caso que ninguém previu: um CROSS JOIN acidental,
# um ORDER BY sobre expressão não indexada.
TIMEOUT_DA_CONSULTA_MS = 3000


@contextmanager
def conexao_de_busca(timeout_ms: int = TIMEOUT_DA_CONSULTA_MS) -> Connection:
    """Conexão para SQL gerado por LLM: somente leitura e com tempo limite.

    A role já não tem permissão de escrita em nada, nem de leitura fora de
    `imoveis` — esta é a camada de profundidade, não a fronteira. `READ ONLY`
    faz o PostgreSQL recusar a escrita antes de tentá-la, e o
    `statement_timeout` impede que uma consulta infeliz segure a conexão
    enquanto alguém espera resposta no WhatsApp.

    Termina sempre em rollback. Não há o que commitar, e deixar o commit fora
    do caminho é uma garantia a menos para manter em dia.
    """
    with engine_busca.connect() as conn:
        # Precisa ser o primeiro comando da transação: o PostgreSQL recusa
        # `SET TRANSACTION` depois que uma consulta já rodou nela.
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        try:
            yield conn
        finally:
            conn.rollback()
