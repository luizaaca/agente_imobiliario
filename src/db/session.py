"""Gerenciamento de sessão do banco de dados."""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings

# Ajuste de compatibilidade
engine = create_engine(
    settings.database_url_safe,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
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
