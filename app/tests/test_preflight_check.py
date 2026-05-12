from app.config import Settings
import scripts.preflight_check as preflight


def _settings() -> Settings:
    s = Settings()
    s.debug = False
    s.telegram_bot_token = "token"
    s.allowed_telegram_user_ids = "1"
    s.user_id_hash_salt = "salt-value-1234567890"
    s.web_owner_password = "long-password-123456"
    s.web_owner_token = "owner-token-1234567890"
    s.web_session_secret = "session-secret-1234567890"
    s.llm_primary_provider = "mock"
    s.llm_fallback_provider = "mock"
    return s


def test_preflight_fails_when_mock_embeddings_in_prod(monkeypatch):
    settings = _settings()
    settings.app_env = "prod"
    settings.llm_embeddings_provider = "mock"
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    rows = preflight.check_env()
    assert ("fail", "APP_ENV=prod requires LLM_EMBEDDINGS_PROVIDER to be non-mock (openai|openrouter|groq|gemini)") in rows


def test_preflight_fails_when_embeddings_key_missing_in_prod(monkeypatch):
    settings = _settings()
    settings.app_env = "prod"
    settings.llm_embeddings_provider = "openai"
    settings.openai_api_key = ""
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    rows = preflight.check_env()
    assert ("fail", "APP_ENV=prod missing API key for embeddings provider: openai") in rows


def test_preflight_warns_when_embeddings_mock_outside_prod(monkeypatch):
    settings = _settings()
    settings.app_env = "dev"
    settings.llm_embeddings_provider = "mock"
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    rows = preflight.check_env()
    assert ("warn", "embeddings provider is mock (allowed outside APP_ENV=prod)") in rows
