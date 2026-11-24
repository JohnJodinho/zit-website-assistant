from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
from app.chat.generation import begin_generation
from app.chat.providers import ProviderError, StreamingProvider, Usage
from app.chat.quota import QuotaManager
from app.config import Settings


class FakeProvider:
    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure
        self.calls = 0
        self.prompts: list[str] = []

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncGenerator[tuple[str, Usage | None], None]:
        self.calls += 1
        self.prompts.append(prompt)
        if self.failure:
            raise ProviderError("unavailable", 503)
        yield "answer", None
        yield "", Usage(10, 4)


def _model(
    model: str,
    provider: str,
    tier: int,
    *,
    enabled: bool = True,
    free_confirmed: bool = True,
) -> dict[str, object]:
    return {
        "model": model,
        "provider": provider,
        "tier": tier,
        "enabled": enabled,
        "free_confirmed": free_confirmed,
        "rpm": 30,
        "rpd": 100,
        "tpm": 8000,
        "tpd": 200000,
    }


async def test_generation_fails_over_before_first_content() -> None:
    settings = Settings(
        _env_file=None,
        llm_models=json.dumps([_model("first", "groq", 1), _model("second", "gemini", 2)]),
    )
    providers: dict[str, StreamingProvider] = {
        "groq": FakeProvider(failure=True),
        "gemini": FakeProvider(),
    }

    generation, failures = await begin_generation(
        settings,
        providers,
        QuotaManager(),
        "A short prompt",
    )

    assert generation is not None
    assert generation.model_id == "second"
    assert generation.first_text == "answer"
    assert [failure.error_class for failure in failures] == ["unavailable"]
    assert providers["groq"].calls == 1
    assert providers["gemini"].calls == 1
    assert providers["gemini"].prompts == ["A short prompt"]


async def test_generation_never_calls_models_without_both_free_flags() -> None:
    settings = Settings(
        _env_file=None,
        llm_models=json.dumps(
            [
                _model("disabled", "groq", 1, enabled=False),
                _model("unconfirmed", "gemini", 2, free_confirmed=False),
                _model("eligible", "groq", 3),
            ]
        ),
    )
    provider = FakeProvider()
    providers: dict[str, StreamingProvider] = {"groq": provider, "gemini": FakeProvider()}

    generation, failures = await begin_generation(
        settings,
        providers,
        QuotaManager(),
        "A short prompt",
    )

    assert generation is not None
    assert generation.model_id == "eligible"
    assert failures == []
    assert provider.calls == 1
    assert providers["gemini"].calls == 0


async def test_generation_closes_stream_when_cancelled_before_first_text() -> None:
    waiting = asyncio.Event()
    closed = asyncio.Event()

    class WaitingProvider:
        async def stream(
            self,
            *,
            model: str,
            prompt: str,
            max_output_tokens: int,
        ) -> AsyncGenerator[tuple[str, Usage | None], None]:
            try:
                await waiting.wait()
                yield "unreachable", None
            finally:
                closed.set()

    settings = Settings(
        _env_file=None,
        llm_models=json.dumps([_model("model", "groq", 1)]),
    )
    task = asyncio.create_task(
        begin_generation(
            settings,
            {"groq": WaitingProvider()},
            QuotaManager(),
            "A short prompt",
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
