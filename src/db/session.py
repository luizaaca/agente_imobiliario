"""Gerenciamento de sessão do banco de dados."""

from contextlib import contextmanager

from sqlalchemy import create_engine
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
