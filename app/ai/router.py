from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.ai.providers.base import LLMAuthError, LLMProviderError, LLMRateLimitError, LLMResponse, LLMTransientError
from app.ai.validators import PostGenerationValidator
from app.config import Settings
from app.db.models import ModelCall
from app.db.repositories import ModelCallRepo
from app.observability import safe_user_id

logger = logging.getLogger("app.ai.router")
PRICE_PER_1K: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o-mini"): (0.00015, 0.0006),
    ("openai", "gpt-4.1-mini"): (0.0004, 0.0016),
    ("openrouter", "openai/gpt-4o-mini"): (0.0002, 0.0008),
    ("groq", "llama-3.3-70b-versatile"): (0.00059, 0.00079),
    ("groq", "llama-3.1-8b-instant"): (0.00005, 0.00008),
    ("gemini", "gemini-2.0-flash"): (0.0001, 0.0004),
}


class CostLimitExceededError(RuntimeError):
    pass


class CostGuard:
    def __init__(self, settings: Settings):
        self.settings = settings

    def check_request_tokens(self, messages: list[dict[str, str]], max_tokens: int) -> None:
        rough_tokens = max(1, len(" ".join(m.get("content", "") for m in messages)) // 4)
        if rough_tokens > max_tokens:
            raise CostLimitExceededError(f"Request is too large: ~{rough_tokens} tokens > {max_tokens}")

    def check_budget(self, db) -> None:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        daily = db.execute(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.created_at >= day_start)).scalar()
        monthly = db.execute(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.created_at >= month_start)).scalar()
        daily_value = float(daily or 0)
        monthly_value = float(monthly or 0)
        if daily_value >= self.settings.daily_cost_limit_usd:
            raise CostLimitExceededError(f"Daily AI budget exceeded: {daily_value:.4f} USD")
        if monthly_value >= self.settings.monthly_cost_limit_usd:
            raise CostLimitExceededError(f"Monthly AI budget exceeded: {monthly_value:.4f} USD")


class LLMRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        primary,
        fallback,
        classification,
        summary,
        embeddings,
    ):
        self.settings = settings
        self.primary = primary
        self.fallback = fallback
        self.classification = classification
        self.summary = summary
        self.embeddings = embeddings
        self.cost_guard = CostGuard(settings)
        self.validator = PostGenerationValidator()

    async def generate(
        self,
        db,
        user_id,
        prompt: str | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        system_prompt: str = "",
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        purpose: str = "answer",
    ) -> str:
        payload_messages = messages or [{"role": "user", "content": prompt or ""}]
        selected_primary, selected_fallback, model = self._providers_for_purpose(purpose, payload_messages, metadata or {})
        self.cost_guard.check_budget(db)
        self.cost_guard.check_request_tokens(payload_messages, self.settings.llm_max_request_tokens)
        last_error: Exception | None = None
        for provider in (selected_primary, selected_fallback):
            if provider is None:
                continue
            t0 = time.perf_counter()
            try:
                response = await self._retry_generate(
                    provider=provider,
                    messages=payload_messages,
                    system_prompt=system_prompt,
                    response_format=response_format,
                    tools=tools,
                    metadata={**(metadata or {}), "purpose": purpose, "model": model},
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                validated = self.validator.validate(question=payload_messages[-1].get("content", ""), answer=response.text)
                response.text = validated.rewritten_answer
                self._log_call(db, user_id, response, purpose, latency_ms, "ok")
                self._log_structured("ok", provider.name, model, purpose, latency_ms, None, user_id, self.settings.user_id_hash_salt)
                return response.text
            except Exception as exc:
                last_error = exc
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._log_call(
                    db,
                    user_id,
                    LLMResponse(text="", model=model, provider=provider.name),
                    purpose,
                    latency_ms,
                    "failed",
                )
                self._log_structured("failed", provider.name, model, purpose, latency_ms, str(exc), user_id, self.settings.user_id_hash_salt)
                continue
        if isinstance(last_error, LLMAuthError):
            return f"Ошибка AI-конфигурации: {last_error}"
        return "Извините, AI-провайдеры временно недоступны."

    async def embed(self, db, user_id, texts: list[str]) -> list[list[float]]:
        self.cost_guard.check_budget(db)
        provider = self.embeddings
        t0 = time.perf_counter()
        try:
            vectors = await provider.embed(texts, metadata={"purpose": "embeddings"})
        except (LLMAuthError, LLMProviderError, LLMTransientError, LLMRateLimitError):
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._log_call(
                db,
                user_id,
                LLMResponse(text="", model=self.settings.llm_embeddings_model, provider=provider.name),
                "embeddings",
                latency_ms,
                "failed",
            )
            return []
        latency_ms = int((time.perf_counter() - t0) * 1000)
        self._log_call(
            db,
            user_id,
            LLMResponse(text="", model=self.settings.llm_embeddings_model, provider=provider.name),
            "embeddings",
            latency_ms,
            "ok",
        )
        self._log_structured("ok", provider.name, self.settings.llm_embeddings_model, "embeddings", latency_ms, None, user_id, self.settings.user_id_hash_salt)
        return vectors

    async def transcribe(self, db, user_id, audio_bytes: bytes, filename: str) -> str:
        provider = self.primary
        if hasattr(provider, "transcribe"):
            text = await provider.transcribe(audio_bytes=audio_bytes, filename=filename, metadata={"purpose": "transcription"})
            return (text or "").strip()
        return ""

    async def ocr(self, db, user_id, image_bytes: bytes, filename: str) -> str:
        provider = self.primary
        if hasattr(provider, "ocr"):
            text = await provider.ocr(image_bytes=image_bytes, filename=filename, metadata={"purpose": "ocr"})
            return (text or "").strip()
        return ""

    async def vision_describe(self, db, user_id, image_bytes: bytes, filename: str) -> str:
        provider = self.primary
        if hasattr(provider, "describe_image"):
            text = await provider.describe_image(image_bytes=image_bytes, filename=filename, metadata={"purpose": "vision"})
            return (text or "").strip()
        return ""

    async def _retry_generate(self, *, provider, messages, system_prompt, response_format, tools, metadata) -> LLMResponse:
        attempts = max(1, self.settings.llm_retry_attempts)
        backoff = max(0.0, self.settings.llm_retry_backoff_s)
        for attempt in range(1, attempts + 1):
            try:
                return await provider.generate(messages, system_prompt, response_format=response_format, tools=tools, metadata=metadata)
            except (LLMRateLimitError, LLMTransientError, asyncio.TimeoutError):
                if attempt >= attempts:
                    raise
                await asyncio.sleep(backoff * attempt)
            except LLMProviderError:
                raise

    def _providers_for_purpose(self, purpose: str, messages: list[dict[str, str]], metadata: dict[str, Any]):
        if purpose == "answer":
            text = " ".join(m.get("content", "") for m in messages).lower()
            high_risk = any(
                token in text
                for token in ("доз", "mg/kg", "мг/кг", "парацетамол", "отрав", "не дыш", "без сознания", "взаимодейств", "клиническ")
            )
            if high_risk and self.settings.llm_high_risk_provider and self.settings.llm_high_risk_model:
                from app.services import _build_provider

                p = _build_provider(self.settings.llm_high_risk_provider, self.settings.llm_high_risk_model, self.settings)
                return p, self.fallback, self.settings.llm_high_risk_model
            if (not high_risk) and self.settings.llm_low_risk_provider and self.settings.llm_low_risk_model:
                from app.services import _build_provider

                p = _build_provider(self.settings.llm_low_risk_provider, self.settings.llm_low_risk_model, self.settings)
                return p, self.fallback, self.settings.llm_low_risk_model
        if purpose == "classification":
            return self.classification, self.fallback, self.settings.llm_classification_model
        if purpose == "summary":
            return self.summary, self.fallback, self.settings.llm_summary_model
        return self.primary, self.fallback, self.settings.llm_primary_model

    def _model_for_purpose(self, purpose: str) -> str:
        if purpose == "classification":
            return self.settings.llm_classification_model
        if purpose == "summary":
            return self.settings.llm_summary_model
        if purpose == "embeddings":
            return self.settings.llm_embeddings_model
        return self.settings.llm_primary_model

    def _log_call(self, db, user_id, response: LLMResponse, purpose: str, latency_ms: int, status: str) -> None:
        cost = response.cost_usd if response.cost_usd else 0.0
        if cost <= 0 and status == "ok":
            provider = (response.provider or "").lower()
            model = (response.model or "").lower()
            price = PRICE_PER_1K.get((provider, model))
            if price:
                in_cost, out_cost = price
                cost = (float(response.input_tokens or 0) / 1000.0) * in_cost + (float(response.output_tokens or 0) / 1000.0) * out_cost
            else:
                in_rate = float(self.settings.llm_cost_estimate_input_per_1k)
                out_rate = float(self.settings.llm_cost_estimate_output_per_1k)
                cost = (float(response.input_tokens or 0) / 1000.0) * in_rate + (float(response.output_tokens or 0) / 1000.0) * out_rate
        ModelCallRepo(db).add(
            user_id=user_id,
            provider=response.provider,
            model=response.model,
            purpose=purpose,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=Decimal(str(cost)),
            latency_ms=latency_ms,
            status=status,
        )

    @staticmethod
    def _log_structured(
        status: str,
        provider: str,
        model: str,
        purpose: str,
        latency_ms: int,
        error: str | None,
        user_id,
        salt: str,
    ) -> None:
        category = "none"
        if error:
            category = "auth_error" if "auth" in error.lower() else "provider_error"
        logger.info(
            "ai_call",
            extra={
                "event": "ai_call",
                "status": status,
                "provider": provider,
                "model": model,
                "purpose": purpose,
                "latency_ms": latency_ms,
                "error": error,
                "error_category": category,
                "telegram_user_id": safe_user_id(user_id, salt),
            },
        )
