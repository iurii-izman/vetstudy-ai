from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VetStudy AI"
    app_env: str = "dev"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    telegram_bot_token: str = Field(default="", validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"))
    telegram_mode: str = "polling"  # polling|webhook
    webhook_url: str = ""
    webhook_path: str = "/telegram/webhook"
    telegram_chat_id: int = 0
    allowed_telegram_user_ids: str = ""
    allowed_telegram_usernames: str = ""

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/vetstudy"
    redis_url: str = ""
    media_jobs_stream: str = "media:document_index_jobs"
    media_jobs_group: str = "media-indexers"
    media_jobs_consumer: str = ""
    media_jobs_block_ms: int = 1000
    media_jobs_reclaim_idle_ms: int = 900_000
    media_jobs_stall_warn_after_s: int = 600
    media_jobs_stall_pending_threshold: int = 10
    media_jobs_stall_log_interval_s: int = 60
    media_storage_path: str = "./data/uploads"
    max_voice_file_size_bytes: int = 20 * 1024 * 1024
    max_image_file_size_bytes: int = 10 * 1024 * 1024
    max_document_file_size_bytes: int = 30 * 1024 * 1024
    multimodal_ocr_enabled: bool = False
    multimodal_vision_enabled: bool = False

    llm_primary_provider: str = "mock"
    llm_fallback_provider: str = "mock"
    llm_primary_model: str = "mock-primary"
    llm_fallback_model: str = "mock-fallback"
    llm_classification_provider: str = "mock"
    llm_classification_model: str = "mock-classifier"
    llm_summary_provider: str = "mock"
    llm_summary_model: str = "mock-summary"
    llm_embeddings_provider: str = "mock"
    llm_embeddings_model: str = "mock-embeddings"
    llm_request_timeout_s: float = 30.0
    llm_retry_attempts: int = 2
    llm_retry_backoff_s: float = 0.5
    llm_circuit_breaker_failures: int = 2
    llm_circuit_breaker_open_seconds: float = 20.0
    llm_enable_gemini_route_boosters: bool = True
    llm_max_request_tokens: int = 4096
    llm_max_output_tokens_default: int = 700
    llm_max_output_tokens_low_risk: int = 520
    llm_max_output_tokens_high_risk: int = 340
    llm_max_output_tokens_dosage: int = 260
    llm_max_output_tokens_toxicology: int = 260
    llm_max_output_tokens_emergency: int = 220
    llm_low_risk_provider: str = "gemini"
    llm_low_risk_model: str = "gemini-2.5-flash-lite"
    llm_high_risk_provider: str = "openai"
    llm_high_risk_model: str = "gpt-5.4-mini"
    llm_cost_estimate_input_per_1k: float = 0.0005
    llm_cost_estimate_output_per_1k: float = 0.0015

    openai_api_key: str = Field(default="", validation_alias=AliasChoices("OPENAI_API_KEY"))
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("OPENAI_BASE_URL"))
    gemini_api_key: str = Field(default="", validation_alias=AliasChoices("GEMINI_API_KEY"))
    openrouter_api_key: str = Field(default="", validation_alias=AliasChoices("OPENROUTER_API_KEY"))
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", validation_alias=AliasChoices("OPENROUTER_BASE_URL"))
    groq_api_key: str = Field(default="", validation_alias=AliasChoices("GROQ_API_KEY"))
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", validation_alias=AliasChoices("GROQ_BASE_URL"))

    daily_cost_limit_usd: float = Field(default=2.0, validation_alias=AliasChoices("DAILY_COST_LIMIT_USD", "DAILY_COST_CAP_USD"))
    monthly_cost_limit_usd: float = Field(default=25.0, validation_alias=AliasChoices("MONTHLY_COST_LIMIT_USD", "MONTHLY_COST_CAP_USD"))
    weekly_cost_budget_usd: float = Field(default=0.0, validation_alias=AliasChoices("WEEKLY_COST_BUDGET_USD"))
    weekly_cost_alarm_ratio: float = Field(default=0.8, validation_alias=AliasChoices("WEEKLY_COST_ALARM_RATIO"))
    global_daily_cost_limit_usd: float = Field(default=2.0, validation_alias=AliasChoices("GLOBAL_DAILY_COST_LIMIT_USD"))
    global_monthly_cost_limit_usd: float = Field(default=25.0, validation_alias=AliasChoices("GLOBAL_MONTHLY_COST_LIMIT_USD"))
    user_id_hash_salt: str = ""
    web_owner_telegram_id: int = Field(default=0, validation_alias=AliasChoices("WEB_OWNER_TELEGRAM_ID"))
    web_owner_password: str = "vetstudy-owner"
    web_owner_password_hash: str = ""
    web_owner_token: str = "vetstudy-local-token"
    web_session_secret: str = "change-me-session-secret"
    web_session_ttl_seconds: int = 900
    web_login_rate_limit_count: int = 8
    web_login_rate_limit_window_seconds: int = 300
    web_admin_rate_limit_count: int = 120
    web_admin_rate_limit_window_seconds: int = 60
    sentry_dsn: str = ""
    evidence_sources_path: str = "quality/evidence_sources/sources.json"

    @property
    def allowed_user_ids(self) -> set[int]:
        if not self.allowed_telegram_user_ids.strip():
            return set()
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(",") if x.strip()}

    @property
    def allowed_usernames(self) -> set[str]:
        if not self.allowed_telegram_usernames.strip():
            return set()
        return {x.strip().lstrip("@").lower() for x in self.allowed_telegram_usernames.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
