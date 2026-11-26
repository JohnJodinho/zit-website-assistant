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


@dataclass(frozen=True, slots=True)
class ProviderUpdate:
    usage: Usage | None = None
    finish_reason: str | None = None


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
    ) -> AsyncGenerator[tuple[str, ProviderUpdate | None], None]: ...


def _finish_reason_name(value: object) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    return name if isinstance(name, str) else str(value)


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
    ) -> AsyncGenerator[tuple[str, ProviderUpdate | None], None]:
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
                finish_reason = None
                if choices:
                    choice = choices[0]
                    finish_reason = _finish_reason_name(getattr(choice, "finish_reason", None))
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    if content:
                        yield str(content), None
                usage = getattr(event, "usage", None)
                usage_update = None
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                    usage_update = Usage(int(prompt_tokens), int(completion_tokens))
                if finish_reason is not None or usage_update is not None:
                    yield (
                        "",
                        ProviderUpdate(
                            usage=usage_update,
                            finish_reason=finish_reason,
                        ),
                    )
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
    ) -> AsyncGenerator[tuple[str, ProviderUpdate | None], None]:
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=model,
                contents=prompt,
                config={"max_output_tokens": max_output_tokens},
            )
            async for event in stream:
                finish_reason = None
                for candidate in getattr(event, "candidates", None) or ():
                    candidate_reason = _finish_reason_name(
                        getattr(candidate, "finish_reason", None)
                    )
                    if candidate_reason is not None:
                        finish_reason = candidate_reason
                    content = getattr(candidate, "content", None)
                    for part in getattr(content, "parts", None) or ():
                        if getattr(part, "thought", False):
                            continue
                        text = getattr(part, "text", None)
                        if text:
                            yield str(text), None
                usage = getattr(event, "usage_metadata", None)
                usage_update = None
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                    response_tokens = getattr(usage, "response_token_count", None)
                    if response_tokens is None:
                        response_tokens = getattr(usage, "candidates_token_count", 0)
                    response_tokens = response_tokens or 0
                    thought_tokens = getattr(usage, "thoughts_token_count", 0) or 0
                    usage_update = Usage(
                        int(prompt_tokens),
                        int(response_tokens) + int(thought_tokens),
                    )
                if finish_reason is not None or usage_update is not None:
                    yield (
                        "",
                        ProviderUpdate(
                            usage=usage_update,
                            finish_reason=finish_reason,
                        ),
                    )
        except GeminiAPIError as exc:
            raise ProviderError(type(exc).__name__, getattr(exc, "code", None)) from exc
