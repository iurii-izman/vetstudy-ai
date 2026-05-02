from __future__ import annotations

from typing import Any

import httpx

from app.ai.providers.base import LLMAuthError, LLMRateLimitError, LLMResponse, LLMTransientError


class DisabledProvider:
    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None) -> LLMResponse:
        raise LLMAuthError(f"{self.name} provider disabled: {self.reason}")

    async def embed(self, texts, metadata=None) -> list[list[float]]:
        raise LLMAuthError(f"{self.name} provider disabled: {self.reason}")

    def estimate_cost(self, response: LLMResponse) -> float | None:
        return response.cost_usd


class OpenAICompatProvider:
    def __init__(self, *, name: str, base_url: str, api_key: str, model: str, timeout_s: float = 30.0):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None) -> LLMResponse:
        if not self.api_key:
            raise LLMAuthError(f"{self.name} API key is missing")
        payload_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        payload: dict[str, Any] = {"model": self.model, "messages": payload_messages}
        if metadata and metadata.get("max_tokens"):
            payload["max_tokens"] = int(metadata["max_tokens"])
        if metadata and metadata.get("temperature") is not None:
            payload["temperature"] = float(metadata["temperature"])
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise LLMAuthError(f"{self.name} authentication failed")
            if resp.status_code == 429:
                raise LLMRateLimitError(f"{self.name} rate limited")
            if 400 <= resp.status_code < 500:
                raise LLMTransientError(f"{self.name} client error {resp.status_code}: {resp.text[:300]}")
            if resp.status_code >= 500:
                raise LLMTransientError(f"{self.name} server error {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"{self.name} timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"{self.name} http error") from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content", ""),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            model=data.get("model", self.model),
            provider=self.name,
            usage=usage,
        )

    async def embed(self, texts, metadata=None) -> list[list[float]]:
        if not self.api_key:
            raise LLMAuthError(f"{self.name} API key is missing")
        payload = {"model": self.model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise LLMAuthError(f"{self.name} authentication failed")
            if resp.status_code == 429:
                raise LLMRateLimitError(f"{self.name} rate limited")
            if 400 <= resp.status_code < 500:
                raise LLMTransientError(f"{self.name} client error {resp.status_code}: {resp.text[:300]}")
            if resp.status_code >= 500:
                raise LLMTransientError(f"{self.name} server error {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"{self.name} timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"{self.name} http error") from exc
        return [item.get("embedding", []) for item in data.get("data", [])]

    async def transcribe(self, audio_bytes: bytes, filename: str, metadata=None) -> str:
        if not self.api_key:
            raise LLMAuthError(f"{self.name} API key is missing")
        files = {"file": (filename, audio_bytes), "model": (None, self.model)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    files=files,
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise LLMAuthError(f"{self.name} authentication failed")
            if resp.status_code == 429:
                raise LLMRateLimitError(f"{self.name} rate limited")
            if 400 <= resp.status_code < 500:
                raise LLMTransientError(f"{self.name} client error {resp.status_code}: {resp.text[:300]}")
            if resp.status_code >= 500:
                raise LLMTransientError(f"{self.name} server error {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"{self.name} timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"{self.name} http error") from exc
        return data.get("text", "")

    def estimate_cost(self, response: LLMResponse) -> float | None:
        return response.cost_usd

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://vetstudy.local"
            headers["X-Title"] = "VetStudy AI"
        return headers


class GeminiProvider:
    def __init__(self, *, model: str, api_key: str, timeout_s: float = 30.0):
        self.name = "gemini"
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None) -> LLMResponse:
        if not self.api_key:
            raise LLMAuthError("gemini API key is missing")
        contents = []
        for m in messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt or ""}]},
            "contents": contents,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/models/{self.model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                )
            if resp.status_code == 401:
                raise LLMAuthError("gemini authentication failed")
            if resp.status_code == 429:
                raise LLMRateLimitError("gemini rate limited")
            if resp.status_code >= 500:
                raise LLMTransientError(f"gemini server error {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTransientError("gemini timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError("gemini http error") from exc
        candidates = data.get("candidates") or []
        parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts") or [])
        text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
            model=self.model,
            provider=self.name,
            usage=usage,
        )

    async def embed(self, texts, metadata=None) -> list[list[float]]:
        if not self.api_key:
            raise LLMAuthError("gemini API key is missing")
        vectors: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                for text in texts:
                    resp = await client.post(
                        f"{self.base_url}/models/{self.model}:embedContent",
                        params={"key": self.api_key},
                        json={"content": {"parts": [{"text": text}]}}
                    )
                    if resp.status_code == 401:
                        raise LLMAuthError("gemini authentication failed")
                    if resp.status_code == 429:
                        raise LLMRateLimitError("gemini rate limited")
                    if resp.status_code >= 500:
                        raise LLMTransientError(f"gemini server error {resp.status_code}")
                    resp.raise_for_status()
                    data = resp.json()
                    vectors.append(((data.get("embedding") or {}).get("values")) or [])
        except httpx.TimeoutException as exc:
            raise LLMTransientError("gemini timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError("gemini http error") from exc
        return vectors

    def estimate_cost(self, response: LLMResponse) -> float | None:
        return response.cost_usd
