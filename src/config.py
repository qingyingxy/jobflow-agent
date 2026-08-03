from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    app_name: str = "JobFlow Agent"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/jobflow.db"
    default_user_id: str = "local-user"
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    structured_model_provider: str = "fake"
    llm_base_url: str | None = None
    llm_response_format: str = "auto"
    llm_timeout_seconds: float = 30.0
    prompt_version: str = "jd-parser-prompt-v2"
    parser_version: str = "jd-parser-v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
