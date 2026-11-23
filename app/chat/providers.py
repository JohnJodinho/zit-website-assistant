from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from google import genai
from groq import AsyncGroq


@dataclass(frozen=True, slots=True)
class Usage:
    tokens_in: int
    tokens_out: int


class StreamingProvider(Protocol):
    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncIterator[tuple[str, Usage | None]]: ...


class GroqProvider:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncGroq(api_key=api_key)

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncIterator[tuple[str, Usage | None]]:
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_output_tokens,
            stream=True,
        )
        async for event in stream:
            choices = getattr(event, "choices", None)
            if choices:
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    yield str(content), None
            usage = getattr(event, "usage", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                yield "", Usage(prompt_tokens, completion_tokens)


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncIterator[tuple[str, Usage | None]]:
        stream = await self._client.aio.models.generate_content_stream(
            model=model,
            contents=prompt,
            config={"max_output_tokens": max_output_tokens},
        )
        async for event in stream:
            text = getattr(event, "text", None)
            if text:
                yield str(text), None
