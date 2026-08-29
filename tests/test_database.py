import sqlite3

import pytest

from src.config import Settings
from src.infrastructure.database import (
    SQLITE_BUSY_TIMEOUT_MS,
    _engine_options,
    configure_sqlite_connection,
)


def test_default_database_is_local_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert Settings(_env_file=None).database_url == "sqlite:///./data/jobflow.db"


def test_non_sqlite_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="SQLite-only"):
        _engine_options("postgresql://jobflow:jobflow@localhost/jobflow")


def test_sqlite_connection_enables_integrity_and_concurrency_pragmas(
    tmp_path,
) -> None:
    connection = sqlite3.connect(tmp_path / "pragmas.db")
    try:
        configure_sqlite_connection(connection, None)

        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (
            SQLITE_BUSY_TIMEOUT_MS,
        )
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        connection.close()
