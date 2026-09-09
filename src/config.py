from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    app_name: str = "JobFlow Agent"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/jobflow.db"
    default_user_id: str = "local-user"
    private_storage_dir: str = "./data/private"
    resume_max_bytes: int = 5 * 1024 * 1024
    account_export_max_bytes: int = 100 * 1024 * 1024
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    auth_mode: str = "local"
    allow_insecure_user_header: bool = True
    trusted_identity_header: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256"
    oidc_jwks_cache_seconds: int = 300
    oidc_clock_skew_seconds: int = 30
    oidc_http_timeout_seconds: float = 5.0
    discovery_run_timeout_seconds: int = 3600
    web_search_provider: str = "auto"
    tavily_api_key: str | None = None
    ats_authorization_ttl_seconds: int = 600
    log_level: str = "INFO"
    url_fetch_proxy: str | None = None
    url_fetch_proxy_allow_unlisted_hosts: bool = False
    structured_model_provider: str = "fake"
    llm_base_url: str | None = None
    llm_response_format: str = "auto"
    llm_thinking_mode: str = "auto"
    llm_reasoning_effort: str = "auto"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1.5
    parser_validation_retries: int = 1
    product_prompt_version: str = "product-jd-two-stage-v6"
    product_parser_version: str = "product-jd-parser-v3"
    prompt_version: str = "jd-parser-prompt-v4"
    parser_version: str = "jd-parser-v3"
    core_prompt_version: str = "jd-core-parser-prompt-v24"
    core_parser_version: str = "jd-core-parser-v39"
    detail_prompt_version: str = "jd-detail-parser-prompt-v1"
    staged_prompt_version: str = "jd-staged-parser-prompt-v2"
    staged_parser_version: str = "jd-staged-parser-v17"
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
