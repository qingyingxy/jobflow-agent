from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


settings = get_settings()
SQLITE_BUSY_TIMEOUT_MS = 5_000


def configure_sqlite_connection(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    """Enable the durability and integrity settings required by the local app."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _engine_options(database_url: str) -> dict[str, object]:
    """Validate the SQLite-only contract and prepare local engine options."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(
            "JobFlow Agent is SQLite-only; DATABASE_URL must use sqlite://"
        )

    database = url.database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)

    return {"connect_args": {"check_same_thread": False}}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **_engine_options(settings.database_url),
)
event.listen(engine, "connect", configure_sqlite_connection)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
