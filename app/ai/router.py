from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.ai.providers.base import LLMAuthError, LLMProviderError, LLMRateLimitError, LLMResponse, LLMTransientError
from app.ai.safety import SafetyGate
from app.ai.validators import PostGenerationValidator
from app.config import Settings
from app.db.models import ModelCall
from app.db.repositories import ModelCallRepo
from app.db.repositories import ErrorEventRepo
from app.observability import safe_user_id

logger = logging.getLogger("app.ai.router")
PRICE_PER_1K: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o-mini"): (0.00015, 0.0006),
    ("openai", "gpt-4.1-mini"): (0.0004, 0.0016),
    ("openai", "gpt-4.1-mini-2025-04-14"): (0.0004, 0.0016),
    ("openai", "gpt-5.4"): (0.0025, 0.015),
    ("openai", "gpt-5.4-2026-03-05"): (0.0025, 0.015),
    ("openai", "gpt-5.4-mini"): (0.00075, 0.0045),
    ("openrouter", "openai/gpt-4o-mini"): (0.0002, 0.0008),
    ("groq", "llama-3.3-70b-versatile"): (0.00059, 0.00079),
    ("groq", "llama-3.1-8b-instant"): (0.00005, 0.00008),
    ("gemini", "gemini-2.0-flash"): (0.0001, 0.0004),
}

PRICE_PREFIX_PER_1K: dict[tuple[str, str], tuple[float, float]] = {
    # Official OpenAI list prices (input/output) represented per 1K tokens.
    ("openai", "gpt-4.1-mini-"): (0.0004, 0.0016),
    ("openai", "gpt-5.4-mini-"): (0.00075, 0.0045),
    ("openai", "gpt-5.4-"): (0.0025, 0.015),
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
    HIGH_RISK_INTENTS = {
        "dosage_request",
        "toxicology",
        "emergency_or_red_flag",
        "drug_interaction",
        "clinical_case",
        "uncertain_source",
    }

    @dataclass
    class _BreakerState:
        state: str = "closed"
        failures: int = 0
        open_until_monotonic: float = 0.0

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
        self._provider_locks: dict[str, asyncio.Semaphore] = {}
        self._breaker_by_provider: dict[tuple[str, str], LLMRouter._BreakerState] = {}

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
        base_metadata = dict(metadata or {})
        providers_chain, route_decision, route_reason = self._providers_for_purpose(purpose, payload_messages, base_metadata)
        max_output_tokens = self._resolve_max_output_tokens(
            purpose=purpose,
            messages=payload_messages,
            metadata=base_metadata,
            route_decision=route_decision,
        )
        if max_output_tokens is not None:
            base_metadata["max_tokens"] = max_output_tokens
        self.cost_guard.check_budget(db)
        self.cost_guard.check_request_tokens(payload_messages, self.settings.llm_max_request_tokens)
        last_error: Exception | None = None
        for idx, provider in enumerate(providers_chain):
            if provider is None:
                continue
            t0 = time.perf_counter()
            model = self._provider_model(provider)
            if not self._breaker_can_attempt(provider=provider, model=model, purpose=purpose, user_id=user_id):
                continue
            fallback_used = idx > 0
            self._log_route_decision(
                route_decision=route_decision,
                reason=route_reason,
                provider=provider.name,
                model=model,
                fallback_used=fallback_used,
                purpose=purpose,
                user_id=user_id,
            )
            try:
                limiter = self._provider_locks.setdefault(provider.name, asyncio.Semaphore(4))
                async with limiter:
                    response = await self._retry_generate(
                        provider=provider,
                        messages=payload_messages,
                        system_prompt=system_prompt,
                        response_format=response_format,
                        tools=tools,
                        metadata={
                            **base_metadata,
                            "purpose": purpose,
                            "model": model,
                            "route_decision": route_decision,
                            "route_reason": route_reason,
                        },
                    )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                validated = self.validator.validate(question=payload_messages[-1].get("content", ""), answer=response.text)
                response.text = validated.rewritten_answer
                self._log_call(db, user_id, response, purpose, latency_ms, "ok")
                self._log_structured("ok", provider.name, model, purpose, latency_ms, None, user_id, self.settings.user_id_hash_salt)
                self._breaker_on_success(provider=provider, model=model, purpose=purpose, user_id=user_id)
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
                ErrorEventRepo(db).add(
                    user_id=user_id,
                    scope="provider",
                    category="provider_call_failed",
                    details={"provider": provider.name, "model": model, "purpose": purpose, "error": str(exc)},
                )
                self._breaker_on_failure(provider=provider, model=model, purpose=purpose, user_id=user_id, error=exc)
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
            high_risk, reason = self._is_high_risk_answer(messages, metadata)
            if high_risk:
                return self._build_high_risk_chain(), "high_risk", reason
            return self._build_low_risk_chain(), "low_risk", reason
        if purpose == "classification":
            return [self.classification, self.fallback], "n/a", "purpose=classification"
        if purpose == "summary":
            return [self.summary, self.fallback], "n/a", "purpose=summary"
        return [self.primary, self.fallback], "n/a", f"purpose={purpose}"

    def _is_high_risk_answer(self, messages: list[dict[str, str]], metadata: dict[str, Any]) -> tuple[bool, str]:
        safety = (metadata or {}).get("safety") or {}
        intent = str(safety.get("intent") or metadata.get("intent") or "").strip()
        risk_tags = safety.get("risk_tags")
        if risk_tags is None:
            risk_tags = metadata.get("risk_tags")
        tags = [str(x).strip() for x in (risk_tags or []) if str(x).strip()]
        if intent in self.HIGH_RISK_INTENTS:
            return True, f"intent={intent}"
        if tags:
            return True, f"risk_tags={','.join(tags)}"

        text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
        gate_result = SafetyGate().check(text)
        if gate_result.intent in self.HIGH_RISK_INTENTS:
            return True, f"intent={gate_result.intent}"
        if gate_result.risk_tags:
            return True, f"risk_tags={','.join(gate_result.risk_tags)}"
        return False, f"intent={gate_result.intent}"

    def _resolve_max_output_tokens(
        self,
        *,
        purpose: str,
        messages: list[dict[str, str]],
        metadata: dict[str, Any],
        route_decision: str,
    ) -> int | None:
        cap = int(self.settings.llm_max_output_tokens_default)
        if purpose == "answer":
            intent = self._infer_intent(messages=messages, metadata=metadata)
            if intent == "dosage_request":
                cap = int(self.settings.llm_max_output_tokens_dosage)
            elif intent == "toxicology":
                cap = int(self.settings.llm_max_output_tokens_toxicology)
            elif intent == "emergency_or_red_flag":
                cap = int(self.settings.llm_max_output_tokens_emergency)
            elif route_decision == "high_risk":
                cap = int(self.settings.llm_max_output_tokens_high_risk)
            else:
                cap = int(self.settings.llm_max_output_tokens_low_risk)

        explicit = metadata.get("max_tokens")
        if explicit is not None:
            try:
                cap = min(cap, int(explicit))
            except (TypeError, ValueError):
                pass

        cap = max(32, cap)
        return min(cap, int(self.settings.llm_max_request_tokens))

    def _infer_intent(self, *, messages: list[dict[str, str]], metadata: dict[str, Any]) -> str:
        safety = dict((metadata or {}).get("safety") or {})
        intent = str(safety.get("intent") or metadata.get("intent") or "").strip()
        if intent:
            return intent
        text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
        return SafetyGate().check(text).intent

    def _build_high_risk_chain(self) -> list[Any]:
        chain: list[Any] = []
        from app.services import _build_provider

        if self.settings.llm_high_risk_provider and self.settings.llm_high_risk_model:
            chain.append(_build_provider(self.settings.llm_high_risk_provider, self.settings.llm_high_risk_model, self.settings))
        if self.settings.gemini_api_key:
            chain.append(_build_provider("gemini", "gemini-2.5-pro", self.settings))
        chain.append(self.fallback)
        return self._dedupe_chain(chain)

    def _build_low_risk_chain(self) -> list[Any]:
        chain: list[Any] = []
        from app.services import _build_provider

        if self.settings.llm_low_risk_provider and self.settings.llm_low_risk_model:
            chain.append(_build_provider(self.settings.llm_low_risk_provider, self.settings.llm_low_risk_model, self.settings))
        if self.settings.gemini_api_key:
            chain.append(_build_provider("gemini", "gemini-2.5-flash", self.settings))
        chain.append(self.fallback)
        return self._dedupe_chain(chain)

    @staticmethod
    def _provider_model(provider: Any) -> str:
        return str(getattr(provider, "model", "") or "unknown-model")

    def _dedupe_chain(self, chain: list[Any]) -> list[Any]:
        unique: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for provider in chain:
            if provider is None:
                continue
            key = (str(getattr(provider, "name", "")), self._provider_model(provider))
            if key in seen:
                continue
            seen.add(key)
            unique.append(provider)
        if unique:
            return unique
        return [self.primary, self.fallback]

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
            price = self._price_per_1k(provider=provider, model=model)
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
    def _price_per_1k(*, provider: str, model: str) -> tuple[float, float] | None:
        exact = PRICE_PER_1K.get((provider, model))
        if exact:
            return exact
        for (pfx_provider, model_prefix), rates in PRICE_PREFIX_PER_1K.items():
            if provider == pfx_provider and model.startswith(model_prefix):
                return rates
        return None

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

    def _log_route_decision(
        self,
        *,
        route_decision: str,
        reason: str,
        provider: str,
        model: str,
        fallback_used: bool,
        purpose: str,
        user_id,
    ) -> None:
        logger.info(
            "route_decision",
            extra={
                "event": "route_decision",
                "route_decision": route_decision,
                "reason": reason,
                "provider": provider,
                "model": model,
                "fallback_used": fallback_used,
                "purpose": purpose,
                "telegram_user_id": safe_user_id(user_id, self.settings.user_id_hash_salt),
            },
        )

    def _breaker_can_attempt(self, *, provider: Any, model: str, purpose: str, user_id) -> bool:
        key = (str(getattr(provider, "name", "")), model)
        breaker = self._breaker_by_provider.setdefault(key, self._BreakerState())
        if breaker.state != "open":
            return True
        now = time.monotonic()
        if now >= breaker.open_until_monotonic:
            breaker.state = "half_open"
            self._log_breaker_state(
                provider=key[0],
                model=model,
                purpose=purpose,
                user_id=user_id,
                state="half_open",
                reason="open_window_elapsed",
                failures=breaker.failures,
            )
            return True
        remaining_ms = int(max(0.0, breaker.open_until_monotonic - now) * 1000)
        self._log_breaker_state(
            provider=key[0],
            model=model,
            purpose=purpose,
            user_id=user_id,
            state="open",
            reason="skipped_due_to_open_breaker",
            failures=breaker.failures,
            open_remaining_ms=remaining_ms,
        )
        return False

    def _breaker_on_success(self, *, provider: Any, model: str, purpose: str, user_id) -> None:
        key = (str(getattr(provider, "name", "")), model)
        breaker = self._breaker_by_provider.setdefault(key, self._BreakerState())
        should_log = breaker.state in {"open", "half_open"} or breaker.failures > 0
        breaker.state = "closed"
        breaker.failures = 0
        breaker.open_until_monotonic = 0.0
        if should_log:
            self._log_breaker_state(
                provider=key[0],
                model=model,
                purpose=purpose,
                user_id=user_id,
                state="closed",
                reason="provider_call_succeeded",
                failures=0,
            )

    def _breaker_on_failure(self, *, provider: Any, model: str, purpose: str, user_id, error: Exception) -> None:
        if not isinstance(error, (LLMRateLimitError, LLMTransientError, asyncio.TimeoutError)):
            return
        key = (str(getattr(provider, "name", "")), model)
        breaker = self._breaker_by_provider.setdefault(key, self._BreakerState())
        threshold = max(1, int(self.settings.llm_circuit_breaker_failures))
        open_seconds = max(1.0, float(self.settings.llm_circuit_breaker_open_seconds))

        if breaker.state == "half_open":
            breaker.state = "open"
            breaker.failures = threshold
            breaker.open_until_monotonic = time.monotonic() + open_seconds
            self._log_breaker_state(
                provider=key[0],
                model=model,
                purpose=purpose,
                user_id=user_id,
                state="open",
                reason=f"half_open_failed:{error.__class__.__name__}",
                failures=breaker.failures,
                open_remaining_ms=int(open_seconds * 1000),
            )
            return

        breaker.failures += 1
        if breaker.failures < threshold:
            return
        breaker.state = "open"
        breaker.open_until_monotonic = time.monotonic() + open_seconds
        self._log_breaker_state(
            provider=key[0],
            model=model,
            purpose=purpose,
            user_id=user_id,
            state="open",
            reason=f"failure_threshold_reached:{error.__class__.__name__}",
            failures=breaker.failures,
            open_remaining_ms=int(open_seconds * 1000),
        )

    def _log_breaker_state(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        user_id,
        state: str,
        reason: str,
        failures: int,
        open_remaining_ms: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "event": "breaker_state",
            "breaker_state": state,
            "reason": reason,
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "failures": failures,
            "telegram_user_id": safe_user_id(user_id, self.settings.user_id_hash_salt),
        }
        if open_remaining_ms is not None:
            payload["open_remaining_ms"] = open_remaining_ms
        logger.info("breaker_state", extra=payload)
