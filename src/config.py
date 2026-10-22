from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    web_search_decision_mode: Literal["rule", "agent"] = "rule"
    web_search_decision_max_calls: int = Field(default=6, ge=0, le=20)
    web_search_decision_timeout_seconds: float = Field(default=12, gt=0, le=60)
    web_search_role_review_enabled: bool = True
    web_search_role_review_max_calls: int = Field(default=12, ge=0, le=30)
    web_search_role_review_batch_size: int = Field(default=2, ge=1, le=3)
    web_search_role_review_concurrency: int = Field(default=2, ge=1, le=3)
    web_search_role_review_timeout_seconds: float = Field(default=15, gt=0, le=60)
    web_search_semantic_enabled: bool = True
    web_search_understanding_mode: Literal["ai", "hybrid"] = "ai"
    web_search_semantic_listing_max_calls: int = Field(default=6, ge=0, le=20)
    web_search_semantic_max_calls: int = Field(default=16, ge=0, le=30)
    web_search_semantic_history_max_calls: int = Field(default=4, ge=0, le=15)
    web_search_semantic_recovery_max_calls: int = Field(default=4, ge=0, le=10)
    web_search_semantic_concurrency: int = Field(default=2, ge=1, le=4)
    web_search_semantic_timeout_seconds: float = Field(default=12, gt=0, le=60)
    web_search_semantic_retry_timeout_seconds: float = Field(default=30, gt=0, le=60)
    web_search_direct_sources_enabled: bool = False
    web_search_max_rounds: int = 6
    web_search_budget_seconds: int = 300
    web_search_request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    web_search_transient_retries: int = Field(default=1, ge=0, le=2)
    web_search_target_jobs: int = 15
    web_search_company_target: int = Field(default=3, ge=1, le=10)
    web_search_company_seconds: float = Field(default=30, gt=0, le=120)
    web_search_company_concurrency: int = Field(default=4, ge=1, le=4)
    web_search_company_batch_size: int = Field(default=6, ge=1, le=10)
    company_discovery_enabled: bool = True
    company_discovery_request_timeout_seconds: float = Field(default=60, gt=0, le=120)
    company_discovery_tool_calls: int = Field(default=1, ge=1, le=3)
    company_discovery_budget_seconds: float = Field(default=90, gt=0, le=90)
    company_discovery_max_candidates: int = Field(default=2, ge=1, le=3)
    web_search_verification_budget_seconds: int = 180
    web_search_verification_item_seconds: int = 60
    web_search_entry_limit: int = 8
    web_search_entry_budget_seconds: float = Field(default=45, gt=0, le=120)
    web_search_entry_item_seconds: float = Field(default=15, gt=0, le=60)
    web_search_entry_empty_limit: int = Field(default=2, ge=1, le=5)
    web_search_entry_max_pages: int = 6
    web_search_entry_max_details: int = Field(default=20, ge=1, le=100)
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
    product_parse_mode: Literal["two_stage", "single_call"] = "two_stage"
    product_prompt_version: str = "product-jd-two-stage-v12"
    product_single_call_prompt_version: str = "product-jd-single-call-v4-inline"
    product_parser_version: str = "product-jd-parser-v10"
    product_parse_transport_retries: int = Field(default=1, ge=0, le=3)
    product_parse_retry_backoff_seconds: float = Field(default=1.5, ge=0, le=10)
    product_parse_run_timeout_seconds: float = Field(default=300, gt=0, le=900)
    product_parse_max_model_calls: int = Field(default=6, ge=1, le=12)
    # Semantic matching sends structured experience to the configured model.
    # Keep local matching until the operator explicitly opts in.
    evidence_matching_mode: Literal["semantic", "local"] = "local"
    evidence_matching_timeout_seconds: float = Field(default=60, gt=0, le=120)
    prompt_version: str = "jd-parser-prompt-v4"
    parser_version: str = "jd-parser-v3"
    core_prompt_version: str = "jd-core-parser-prompt-v24"
    core_parser_version: str = "jd-core-parser-v39"
    detail_prompt_version: str = "jd-detail-parser-prompt-v1"
    staged_prompt_version: str = "jd-staged-parser-prompt-v2"
    staged_parser_version: str = "jd-staged-parser-v17"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    vision_fallback_enabled: bool = True
    vision_model: str | None = None
    vision_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
