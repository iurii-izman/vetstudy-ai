from dataclasses import dataclass
from typing import Any, Protocol


class LLMProviderError(RuntimeError):
    pass


class LLMAuthError(LLMProviderError):
    pass


class LLMRateLimitError(LLMProviderError):
    pass


class LLMTransientError(LLMProviderError):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    provider: str = ""
    usage: dict[str, Any] | None = None


class LLMProvider(Protocol):
    name: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        ...

    async def embed(self, texts: list[str], metadata: dict[str, Any] | None = None) -> list[list[float]]:
        ...

    def estimate_cost(self, response: LLMResponse) -> float | None:
        ...
