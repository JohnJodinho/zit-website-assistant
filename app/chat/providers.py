from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from google import genai
from google.genai.errors import APIError as GeminiAPIError
from groq import AsyncGroq, GroqError


@dataclass(frozen=True, slots=True)
class Usage:
    tokens_in: int
    tokens_out: int


class ProviderError(RuntimeError):
    def __init__(self, error_class: str, status_code: int | None = None) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.status_code = status_code


class StreamingProvider(Protocol):
    def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncGenerator[tuple[str, Usage | None], None]: ...


class GroqProvider:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncGroq(api_key=api_key)

    async def close(self) -> None:
        await self._client.close()

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncGenerator[tuple[str, Usage | None], None]:
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_output_tokens,
                stream=True,
                extra_body={"stream_options": {"include_usage": True}},
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
                    yield "", Usage(int(prompt_tokens), int(completion_tokens))
        except GroqError as exc:
            raise ProviderError(type(exc).__name__, getattr(exc, "status_code", None)) from exc


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def close(self) -> None:
        await self._client.aio.aclose()

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncGenerator[tuple[str, Usage | None], None]:
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=model,
                contents=prompt,
                config={"max_output_tokens": max_output_tokens},
            )
            async for event in stream:
                for candidate in getattr(event, "candidates", None) or ():
                    content = getattr(candidate, "content", None)
                    for part in getattr(content, "parts", None) or ():
                        if getattr(part, "thought", False):
                            continue
                        text = getattr(part, "text", None)
                        if text:
                            yield str(text), None
                usage = getattr(event, "usage_metadata", None)
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                    response_tokens = getattr(usage, "response_token_count", 0) or 0
                    thought_tokens = getattr(usage, "thoughts_token_count", 0) or 0
                    yield (
                        "",
                        Usage(
                            int(prompt_tokens),
                            int(response_tokens) + int(thought_tokens),
                        ),
                    )
        except GeminiAPIError as exc:
            raise ProviderError(type(exc).__name__, getattr(exc, "code", None)) from exc
