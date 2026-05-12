import logging

from app.ai.prompts import PromptManager
from app.ai.providers.http_provider import DisabledProvider, GeminiProvider, OpenAICompatProvider
from app.ai.providers.mock import MockProvider
from app.ai.router import LLMRouter
from app.ai.safety import SafetyGate
from app.config import get_settings

logger = logging.getLogger("app.services")


def _build_provider(name: str, model: str, settings):
    provider_name = (name or "mock").lower()
    if provider_name == "mock":
        return MockProvider()
    if provider_name == "openai":
        if not settings.openai_api_key:
            return DisabledProvider("openai", "missing OPENAI_API_KEY")
        return OpenAICompatProvider(
            name="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=model,
            timeout_s=settings.llm_request_timeout_s,
        )
    if provider_name == "openrouter":
        if not settings.openrouter_api_key:
            return DisabledProvider("openrouter", "missing OPENROUTER_API_KEY")
        return OpenAICompatProvider(
            name="openrouter",
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=model,
            timeout_s=settings.llm_request_timeout_s,
        )
    if provider_name == "groq":
        if not settings.groq_api_key:
            return DisabledProvider("groq", "missing GROQ_API_KEY")
        return OpenAICompatProvider(
            name="groq",
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=model,
            timeout_s=settings.llm_request_timeout_s,
        )
    if provider_name == "gemini":
        if not settings.gemini_api_key:
            return DisabledProvider("gemini", "missing GEMINI_API_KEY")
        return GeminiProvider(
            model=model,
            api_key=settings.gemini_api_key,
            timeout_s=settings.llm_request_timeout_s,
        )
    return DisabledProvider(provider_name, "unknown provider")


def build_llm_router() -> LLMRouter:
    settings = get_settings()
    embeddings = _build_provider(settings.llm_embeddings_provider, settings.llm_embeddings_model, settings)
    if settings.app_env == "prod" and settings.llm_embeddings_provider.lower() == "mock":
        logger.warning(
            "prod_mock_embeddings_disabled",
            extra={
                "event": "prod_mock_embeddings_disabled",
                "provider": settings.llm_embeddings_provider,
                "model": settings.llm_embeddings_model,
                "reason": "mock_embeddings_forbidden_in_prod",
            },
        )
        embeddings = DisabledProvider(
            "mock",
            "mock embeddings disabled in APP_ENV=prod; configure LLM_EMBEDDINGS_PROVIDER with a real provider",
        )
    return LLMRouter(
        settings=settings,
        primary=_build_provider(settings.llm_primary_provider, settings.llm_primary_model, settings),
        fallback=_build_provider(settings.llm_fallback_provider, settings.llm_fallback_model, settings),
        classification=_build_provider(settings.llm_classification_provider, settings.llm_classification_model, settings),
        summary=_build_provider(settings.llm_summary_provider, settings.llm_summary_model, settings),
        embeddings=embeddings,
    )


prompt_manager = PromptManager()
safety_gate = SafetyGate()
llm_router = build_llm_router()
