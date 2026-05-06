"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from egw_scout.db.models import Base

DEFAULT_DATABASE_URL = "sqlite:///egw_scout.sqlite3"


class DbapiCursor(Protocol):
    """Minimal DB-API cursor protocol used for SQLite PRAGMAs."""

    def execute(self, statement: str) -> object: ...

    def close(self) -> object: ...


class DbapiConnection(Protocol):
    """Minimal DB-API connection protocol used for SQLite PRAGMAs."""

    def cursor(self) -> DbapiCursor: ...


def create_db_engine(database_url: str = DEFAULT_DATABASE_URL, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    SQLite is the default for local development. The rest of the code only
    depends on SQLAlchemy, so switching to PostgreSQL later should mainly be a
    configuration and migration concern.
    """
    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        if db_path not in {"", ":memory:"}:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, echo=echo, future=True)
    if engine.dialect.name == "sqlite":
        _configure_sqlite(engine)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to an engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def create_tables(engine: Engine) -> None:
    """Create all database tables.

    This is useful for the first SQLite-based version. Once the schema becomes
    stable, Alembic migrations should own schema changes.
    """
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: DbapiConnection, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
