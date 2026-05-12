import asyncio
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ai.providers.base import LLMRateLimitError, LLMResponse
from app.ai.router import LLMRouter
from app.config import Settings
from app.db.models import Base, ModelCall
from app.services import _build_provider


def _make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


class OkProvider:
    name = "ok"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        return LLMResponse(text="primary-ok", model="m1", provider=self.name, input_tokens=10, output_tokens=20, cost_usd=0.01)

    async def embed(self, texts, metadata=None):
        return [[0.1, 0.2] for _ in texts]

    def estimate_cost(self, response):
        return response.cost_usd


class FailingProvider(OkProvider):
    name = "fail"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        raise RuntimeError("boom")


def _settings():
    s = Settings()
    s.llm_retry_attempts = 1
    s.daily_cost_limit_usd = 10.0
    s.monthly_cost_limit_usd = 100.0
    s.llm_circuit_breaker_failures = 2
    s.llm_circuit_breaker_open_seconds = 20.0
    s.gemini_api_key = ""
    s.openai_api_key = ""
    s.openrouter_api_key = ""
    s.groq_api_key = ""
    return s


def test_primary_success():
    db = _make_db()
    router = LLMRouter(settings=_settings(), primary=OkProvider(), fallback=OkProvider(), classification=OkProvider(), summary=OkProvider(), embeddings=OkProvider())
    text = asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="answer"))
    assert "AI-провайдеры временно недоступны" not in text
    calls = list(db.execute(select(ModelCall)).scalars().all())
    assert any(c.status == "ok" for c in calls)


def test_primary_failure_fallback_success():
    db = _make_db()
    router = LLMRouter(settings=_settings(), primary=FailingProvider(), fallback=OkProvider(), classification=OkProvider(), summary=OkProvider(), embeddings=OkProvider())
    text = asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="answer"))
    assert text == "primary-ok"
    calls = list(db.execute(select(ModelCall).order_by(ModelCall.created_at.asc())).scalars().all())
    assert len(calls) == 2
    assert calls[0].status == "failed"
    assert calls[1].status == "ok"


def test_missing_api_key_gives_clear_error():
    settings = _settings()
    provider = _build_provider("openai", "gpt-4o-mini", settings)
    db = _make_db()
    router = LLMRouter(settings=settings, primary=provider, fallback=provider, classification=provider, summary=provider, embeddings=provider)
    text = asyncio.run(router.generate(db, user_id=None, prompt="x"))
    assert "Ошибка AI-конфигурации" in text
    assert "OPENAI_API_KEY" in text


def test_daily_limit_exceeded():
    db = _make_db()
    db.add(ModelCall(provider="mock", model="m", purpose="answer", cost_usd=Decimal("999"), status="ok"))
    db.commit()
    s = _settings()
    s.daily_cost_limit_usd = 1.0
    router = LLMRouter(settings=s, primary=OkProvider(), fallback=OkProvider(), classification=OkProvider(), summary=OkProvider(), embeddings=OkProvider())
    try:
        asyncio.run(router.generate(db, user_id=None, prompt="x"))
        assert False, "expected exception"
    except Exception as exc:
        assert "Daily AI budget exceeded" in str(exc)


def test_model_calls_are_logged():
    db = _make_db()
    router = LLMRouter(settings=_settings(), primary=OkProvider(), fallback=OkProvider(), classification=OkProvider(), summary=OkProvider(), embeddings=OkProvider())
    asyncio.run(router.generate(db, user_id=None, prompt="x"))
    row = db.execute(select(ModelCall).where(ModelCall.status == "ok").order_by(ModelCall.created_at.desc())).scalars().first()
    assert row is not None
    assert row.provider == "ok"
    assert row.input_tokens == 10


class ZeroCostProvider(OkProvider):
    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        return LLMResponse(text="ok", model="unknown-model", provider="unknown-provider", input_tokens=1000, output_tokens=1000, cost_usd=0.0)


class MetadataProbeProvider(OkProvider):
    def __init__(self, name: str = "probe", model: str = "probe-model"):
        self.name = name
        self.model = model
        self.last_metadata = None

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        self.last_metadata = dict(metadata or {})
        return LLMResponse(text="ok", model=self.model, provider=self.name, input_tokens=1, output_tokens=1, cost_usd=0.0)


def test_cost_estimate_used_when_provider_missing_cost():
    db = _make_db()
    s = _settings()
    s.llm_cost_estimate_input_per_1k = 0.01
    s.llm_cost_estimate_output_per_1k = 0.02
    router = LLMRouter(settings=s, primary=ZeroCostProvider(), fallback=ZeroCostProvider(), classification=ZeroCostProvider(), summary=ZeroCostProvider(), embeddings=ZeroCostProvider())
    asyncio.run(router.generate(db, user_id=None, prompt="x"))
    row = db.execute(select(ModelCall).where(ModelCall.status == "ok").order_by(ModelCall.created_at.desc())).scalars().first()
    assert row is not None
    assert float(row.cost_usd) > 0.0


class ZeroCostOpenAISnapshotProvider(OkProvider):
    def __init__(self, model: str):
        self.model = model
        self.name = "openai"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        return LLMResponse(text="ok", model=self.model, provider=self.name, input_tokens=1000, output_tokens=2000, cost_usd=0.0)


def test_openai_snapshot_pricing_uses_prefix_match():
    db = _make_db()
    s = _settings()
    s.llm_cost_estimate_input_per_1k = 0.1
    s.llm_cost_estimate_output_per_1k = 0.2
    router = LLMRouter(
        settings=s,
        primary=ZeroCostOpenAISnapshotProvider("gpt-5.4-mini-2026-03-05"),
        fallback=ZeroCostOpenAISnapshotProvider("gpt-5.4-mini-2026-03-05"),
        classification=ZeroCostOpenAISnapshotProvider("gpt-5.4-mini-2026-03-05"),
        summary=ZeroCostOpenAISnapshotProvider("gpt-5.4-mini-2026-03-05"),
        embeddings=OkProvider(),
    )
    asyncio.run(router.generate(db, user_id=None, prompt="x"))
    row = db.execute(select(ModelCall).where(ModelCall.status == "ok").order_by(ModelCall.created_at.desc())).scalars().first()
    assert row is not None
    # 1K input * 0.00075 + 2K output * 0.0045
    assert abs(float(row.cost_usd) - 0.00975) < 1e-9


def test_openai_snapshot_pricing_uses_exact_match_when_available():
    db = _make_db()
    s = _settings()
    s.llm_cost_estimate_input_per_1k = 0.1
    s.llm_cost_estimate_output_per_1k = 0.2
    router = LLMRouter(
        settings=s,
        primary=ZeroCostOpenAISnapshotProvider("gpt-4.1-mini-2025-04-14"),
        fallback=ZeroCostOpenAISnapshotProvider("gpt-4.1-mini-2025-04-14"),
        classification=ZeroCostOpenAISnapshotProvider("gpt-4.1-mini-2025-04-14"),
        summary=ZeroCostOpenAISnapshotProvider("gpt-4.1-mini-2025-04-14"),
        embeddings=OkProvider(),
    )
    asyncio.run(router.generate(db, user_id=None, prompt="x"))
    row = db.execute(select(ModelCall).where(ModelCall.status == "ok").order_by(ModelCall.created_at.desc())).scalars().first()
    assert row is not None
    # 1K input * 0.0004 + 2K output * 0.0016
    assert abs(float(row.cost_usd) - 0.0036) < 1e-9


def test_output_cap_for_dosage_intent(monkeypatch):
    db = _make_db()
    s = _settings()
    s.llm_max_output_tokens_dosage = 123
    s.gemini_api_key = ""
    probe = MetadataProbeProvider(name="openai", model="gpt-5.4-mini")

    def _build_provider(_name: str, _model: str, _settings):
        return probe

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=s,
        primary=OkProvider(),
        fallback=probe,
        classification=OkProvider(),
        summary=OkProvider(),
        embeddings=OkProvider(),
    )
    asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt="доза амоксициллина для кошки",
            purpose="answer",
            metadata={"safety": {"intent": "dosage_request", "risk_tags": []}},
        )
    )
    assert probe.last_metadata is not None
    assert probe.last_metadata.get("max_tokens") == 123


def test_output_cap_respects_explicit_lower_max_tokens(monkeypatch):
    db = _make_db()
    s = _settings()
    s.llm_max_output_tokens_low_risk = 520
    s.gemini_api_key = ""
    probe = MetadataProbeProvider(name="gemini", model="gemini-2.5-flash-lite")

    def _build_provider(_name: str, _model: str, _settings):
        return probe

    monkeypatch.setattr("app.services._build_provider", _build_provider)

    router = LLMRouter(
        settings=s,
        primary=OkProvider(),
        fallback=probe,
        classification=OkProvider(),
        summary=OkProvider(),
        embeddings=OkProvider(),
    )
    asyncio.run(
        router.generate(
            db,
            user_id=None,
            prompt="объясни воспаление простыми словами",
            purpose="answer",
            metadata={"safety": {"intent": "general_education", "risk_tags": []}, "max_tokens": 90},
        )
    )
    assert probe.last_metadata is not None
    assert probe.last_metadata.get("max_tokens") == 90


def test_answer_purpose_uses_dual_risk_chain_not_injected_primary():
    db = _make_db()
    settings = _settings()
    settings.llm_low_risk_provider = "mock"
    settings.llm_low_risk_model = "mock-low-risk"
    settings.gemini_api_key = ""
    router = LLMRouter(settings=settings, primary=FailingProvider(), fallback=FailingProvider(), classification=OkProvider(), summary=OkProvider(), embeddings=OkProvider())
    text = asyncio.run(router.generate(db, user_id=None, prompt="Объясни тему кратко", purpose="answer"))
    assert text.startswith("[MOCK:answer]")


class RateLimitProvider(OkProvider):
    def __init__(self, *, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0
        self.name = "rate-limit"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMRateLimitError("rate-limit")
        return LLMResponse(text="summary-ok", model="summary-model", provider=self.name, input_tokens=5, output_tokens=5, cost_usd=0.001)


def test_circuit_breaker_opens_and_skips_provider():
    db = _make_db()
    settings = _settings()
    settings.llm_circuit_breaker_failures = 2
    settings.llm_circuit_breaker_open_seconds = 60.0
    summary = RateLimitProvider(fail_times=10)
    router = LLMRouter(
        settings=settings,
        primary=OkProvider(),
        fallback=OkProvider(),
        classification=OkProvider(),
        summary=summary,
        embeddings=OkProvider(),
    )

    asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="summary"))
    asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="summary"))
    text = asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="summary"))

    assert text == "primary-ok"
    assert summary.calls == 2


def test_circuit_breaker_half_open_and_close(caplog):
    db = _make_db()
    settings = _settings()
    settings.llm_circuit_breaker_failures = 1
    settings.llm_circuit_breaker_open_seconds = 1.0
    summary = RateLimitProvider(fail_times=1)
    router = LLMRouter(
        settings=settings,
        primary=OkProvider(),
        fallback=OkProvider(),
        classification=OkProvider(),
        summary=summary,
        embeddings=OkProvider(),
    )

    caplog.set_level("INFO", logger="app.ai.router")

    first = asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="summary"))
    asyncio.run(asyncio.sleep(1.1))
    second = asyncio.run(router.generate(db, user_id=None, prompt="x", purpose="summary"))

    assert first == "primary-ok"
    assert second == "summary-ok"
    states = [getattr(record, "breaker_state", None) for record in caplog.records if getattr(record, "event", "") == "breaker_state"]
    assert "open" in states
    assert "half_open" in states
    assert "closed" in states
