from __future__ import annotations

from contextlib import contextmanager

from sqlmodel import SQLModel, Session, create_engine

from .settings import Settings


def make_engine(settings: Settings):
    # pool_pre_ping helps with Cloud SQL / network blips
    return create_engine(settings.postgres_url, pool_pre_ping=True)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine):
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
