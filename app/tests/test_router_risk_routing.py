import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.providers.base import LLMResponse
from app.ai.router import LLMRouter
from app.config import Settings
from app.db.models import Base


def _make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


class StubProvider:
    def __init__(self, name: str, model: str, *, should_fail: bool = False):
        self.name = name
        self.model = model
        self.should_fail = should_fail

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        if self.should_fail:
            raise RuntimeError(f"{self.name}:{self.model}:boom")
        return LLMResponse(text=f"{self.name}:{self.model}", model=self.model, provider=self.name, input_tokens=5, output_tokens=5, cost_usd=0.001)

    async def embed(self, texts, metadata=None):
        return [[0.1] for _ in texts]


def _settings():
    s = Settings()
    s.llm_retry_attempts = 1
    s.daily_cost_limit_usd = 10.0
    s.monthly_cost_limit_usd = 100.0
    s.llm_low_risk_provider = "gemini"
    s.llm_low_risk_model = "gemini-2.5-flash-lite"
    s.llm_high_risk_provider = "openai"
    s.llm_high_risk_model = "gpt-5.4-mini"
    s.llm_enable_gemini_route_boosters = True
    return s


def test_high_risk_intent_routes_to_paid_model(monkeypatch):
    db = _make_db()
    settings = _settings()
    settings.gemini_api_key = ""

    def _build_provider(name: str, model: str, _settings):
        return StubProvider(name, model)

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=settings,
        primary=StubProvider("primary", "p"),
        fallback=StubProvider("fallback", "f"),
        classification=StubProvider("classification", "c"),
        summary=StubProvider("summary", "s"),
        embeddings=StubProvider("embeddings", "e"),
    )
    text = asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt="вопрос",
            purpose="answer",
            metadata={"safety": {"intent": "dosage_request", "risk_tags": []}},
        )
    )
    assert text == "openai:gpt-5.4-mini"


def test_low_risk_routes_to_free_model(monkeypatch):
    db = _make_db()
    settings = _settings()
    settings.gemini_api_key = ""

    def _build_provider(name: str, model: str, _settings):
        return StubProvider(name, model)

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=settings,
        primary=StubProvider("primary", "p"),
        fallback=StubProvider("fallback", "f"),
        classification=StubProvider("classification", "c"),
        summary=StubProvider("summary", "s"),
        embeddings=StubProvider("embeddings", "e"),
    )
    text = asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt="объясни механизм воспаления",
            purpose="answer",
            metadata={"safety": {"intent": "general_education", "risk_tags": []}},
        )
    )
    assert text == "gemini:gemini-2.5-flash-lite"


def test_high_risk_fallback_uses_gemini_pro_then_default_fallback(monkeypatch):
    db = _make_db()
    settings = _settings()
    settings.gemini_api_key = "configured"

    def _build_provider(name: str, model: str, _settings):
        if name == "openai" and model == "gpt-5.4-mini":
            return StubProvider(name, model, should_fail=True)
        if name == "gemini" and model == "gemini-2.5-pro":
            return StubProvider(name, model)
        return StubProvider(name, model, should_fail=True)

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=settings,
        primary=StubProvider("primary", "p"),
        fallback=StubProvider("fallback", "legacy-fallback", should_fail=True),
        classification=StubProvider("classification", "c"),
        summary=StubProvider("summary", "s"),
        embeddings=StubProvider("embeddings", "e"),
    )
    text = asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt="вопрос",
            purpose="answer",
            metadata={"safety": {"intent": "toxicology", "risk_tags": ["toxic_exposure_common"]}},
        )
    )
    assert text == "gemini:gemini-2.5-pro"


def test_explicit_general_safety_metadata_beats_prompt_policy_noise(monkeypatch):
    db = _make_db()
    settings = _settings()
    settings.gemini_api_key = ""

    def _build_provider(name: str, model: str, _settings):
        return StubProvider(name, model)

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=settings,
        primary=StubProvider("primary", "p"),
        fallback=StubProvider("fallback", "f"),
        classification=StubProvider("classification", "c"),
        summary=StubProvider("summary", "s"),
        embeddings=StubProvider("embeddings", "e"),
    )
    noisy_prompt = (
        "SYSTEM RULES: токсикология, emergency, interaction.\n"
        "User asks: объясни базовый осмотр пациента."
    )
    text = asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt=noisy_prompt,
            purpose="answer",
            metadata={"safety": {"intent": "general_education", "risk_tags": []}},
        )
    )
    assert text.startswith("gemini:gemini-2.5-flash-lite")
