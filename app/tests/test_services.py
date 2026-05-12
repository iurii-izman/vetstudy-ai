from app.ai.providers.http_provider import DisabledProvider
from app.ai.providers.mock import MockProvider
from app.config import Settings
from app.services import build_llm_router


def _settings() -> Settings:
    s = Settings()
    s.gemini_api_key = ""
    s.openai_api_key = ""
    s.openrouter_api_key = ""
    s.groq_api_key = ""
    return s


def test_build_llm_router_blocks_mock_embeddings_in_prod(monkeypatch):
    settings = _settings()
    settings.app_env = "prod"
    settings.llm_embeddings_provider = "mock"
    settings.llm_embeddings_model = "mock-embeddings"
    monkeypatch.setattr("app.services.get_settings", lambda: settings)

    router = build_llm_router()
    assert isinstance(router.embeddings, DisabledProvider)


def test_build_llm_router_keeps_mock_embeddings_in_dev(monkeypatch):
    settings = _settings()
    settings.app_env = "dev"
    settings.llm_embeddings_provider = "mock"
    settings.llm_embeddings_model = "mock-embeddings"
    monkeypatch.setattr("app.services.get_settings", lambda: settings)

    router = build_llm_router()
    assert isinstance(router.embeddings, MockProvider)
