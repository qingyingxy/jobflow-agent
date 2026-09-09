from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import applications as applications_api
from src.api import jobs as jobs_api
from src.api import materials as materials_api
from src.config import Settings
from src.infrastructure.database import Base, get_session
from src.main import app


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(test_engine)


@pytest.fixture(autouse=True)
def override_database_session(db_session: Session) -> Generator[None, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def override_api_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep API regression tests offline even when the developer has real .env keys."""

    settings = Settings(
        structured_model_provider="fake",
        prompt_version="test-prompt-v1",
        parser_version="test-parser-v1",
    )
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    monkeypatch.setattr(applications_api, "get_settings", lambda: settings)
    monkeypatch.setattr(materials_api, "get_settings", lambda: settings)
