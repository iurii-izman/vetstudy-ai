from app.ai.providers.base import LLMResponse


class MockProvider:
    name = "mock"

    async def generate(self, messages, system_prompt, response_format=None, tools=None, metadata=None) -> LLMResponse:
        purpose = (metadata or {}).get("purpose", "answer")
        prompt = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
        preview = f"{system_prompt}\n{prompt}"[:300]
        return LLMResponse(
            text=f"[MOCK:{purpose}] {preview}",
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=120,
            cost_usd=0.0,
            model=(metadata or {}).get("model", "mock-model"),
            provider=self.name,
            usage={"input_tokens": max(1, len(prompt) // 4), "output_tokens": 120},
        )

    async def embed(self, texts, metadata=None) -> list[list[float]]:
        return [[float((len(t) + i) % 100) / 100.0 for i in range(1536)] for t in texts]

    async def transcribe(self, audio_bytes: bytes, filename: str, metadata=None) -> str:
        return f"[MOCK transcript from {filename}]"

    async def ocr(self, image_bytes: bytes, filename: str, metadata=None) -> str:
        return f"[MOCK OCR from {filename}]"

    async def describe_image(self, image_bytes: bytes, filename: str, metadata=None) -> str:
        return f"[MOCK vision description for {filename}]"

    def estimate_cost(self, response: LLMResponse) -> float | None:
        return response.cost_usd
