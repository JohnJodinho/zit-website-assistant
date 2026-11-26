from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.chat.cache import AnswerCache
from app.chat.generation import MAX_OUTPUT_TOKENS
from app.chat.providers import ProviderUpdate, Usage
from app.chat.quota import QuotaManager
from app.chat.retrieval import ChatPlan
from app.chat.streaming import (
    ClientDisconnected,
    _emit_complete_sentences,
    _output_limit_reached,
    _provider_events,
    stream_chat,
)
from app.config import Settings
from app.db.models import LLMCall


def test_complete_sentence_extraction_keeps_unfinished_tail() -> None:
    remaining, sentences = _emit_complete_sentences("One. Two! Tail")

    assert sentences == ["One.", "Two!"]
    assert remaining == "Tail"


@pytest.mark.parametrize(
    ("finish_reason", "tokens_out"),
    [
        ("length", 10),
        ("MAX_TOKENS", 10),
        (None, MAX_OUTPUT_TOKENS),
    ],
)
def test_output_limit_is_detected_from_provider_reason_or_usage(
    finish_reason: str | None,
    tokens_out: int,
) -> None:
    generation = SimpleNamespace(
        finish_reason=finish_reason,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        usage=SimpleNamespace(tokens_out=tokens_out),
    )

    assert _output_limit_reached(generation)


async def test_provider_events_emit_sse_ping_during_slow_stream() -> None:
    async def provider_stream():
        await asyncio.sleep(0.03)
        yield "answer", None

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(sse_ping_seconds=0.005))
        ),
        is_disconnected=lambda: asyncio.sleep(0, result=False),
    )
    generation = SimpleNamespace(stream=provider_stream())

    events = [event async for event in _provider_events(request, generation)]

    assert None in events
    assert ("answer", None) in events


async def test_provider_events_stop_when_client_disconnects() -> None:
    async def provider_stream():
        await asyncio.Event().wait()
        yield "unreachable", None

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(sse_ping_seconds=5))),
        is_disconnected=lambda: asyncio.sleep(0, result=True),
    )
    generation = SimpleNamespace(stream=provider_stream())

    with pytest.raises(ClientDisconnected):
        await asyncio.wait_for(anext(_provider_events(request, generation)), timeout=1)


async def test_ten_fake_provider_streams_complete_concurrently() -> None:
    active = 0
    peak_active = 0

    async def stream_one(index: int) -> list[tuple[str, None] | None]:
        async def provider_stream():
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.01)
            yield f"answer-{index}", None
            active -= 1

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(settings=SimpleNamespace(sse_ping_seconds=1))
            ),
            is_disconnected=lambda: asyncio.sleep(0, result=False),
        )
        generation = SimpleNamespace(stream=provider_stream())
        return [event async for event in _provider_events(request, generation)]

    results = await asyncio.gather(*(stream_one(index) for index in range(10)))

    assert peak_active == 10
    assert all((f"answer-{index}", None) in results[index] for index in range(10))


async def test_output_limit_is_reported_as_incomplete_and_saved_to_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        llm_models=json.dumps(
            [
                {
                    "model": "test-model",
                    "provider": "groq",
                    "tier": 1,
                    "enabled": True,
                    "free_confirmed": True,
                    "rpm": 30,
                    "rpd": 100,
                    "tpm": 8000,
                    "tpd": 200000,
                }
            ]
        ),
    )

    class FakeProvider:
        async def stream(
            self,
            *,
            model: str,
            prompt: str,
            max_output_tokens: int,
        ) -> AsyncGenerator[tuple[str, ProviderUpdate | None], None]:
            assert model == "test-model"
            assert prompt == "a test prompt"
            assert max_output_tokens == MAX_OUTPUT_TOKENS
            yield "The first sentence is complete. ", None
            yield (
                "",
                ProviderUpdate(
                    usage=Usage(100, MAX_OUTPUT_TOKENS),
                    finish_reason="length",
                ),
            )

    class FakeSession:
        async def commit(self) -> None:
            return None

    async def prepare_plan(*_: object) -> ChatPlan:
        return ChatPlan(
            path="retrieval",
            intent=("courses",),
            answer=None,
            prompt="a test prompt",
            links=(),
            hits=(),
            degraded=False,
            confidence={},
        )

    records: list[LLMCall] = []

    async def persist_calls(_: object, calls: list[LLMCall]) -> None:
        records.extend(calls)

    monkeypatch.setattr("app.chat.streaming.prepare_chat_plan", prepare_plan)
    monkeypatch.setattr("app.chat.streaming.get_providers", lambda _: {"groq": FakeProvider()})
    monkeypatch.setattr("app.chat.streaming.answer_is_grounded", lambda *_: True)
    monkeypatch.setattr("app.chat.streaming._persist_llm_calls", persist_calls)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=settings,
                active_snapshot=None,
                answer_cache=AnswerCache(),
                quota_manager=QuotaManager(),
                session_factory=None,
            )
        ),
        is_disconnected=lambda: asyncio.sleep(0, result=False),
    )
    session_record = SimpleNamespace(turn_count=0, last_seen_at=None)

    events = [
        event
        async for event in stream_chat(
            request,
            FakeSession(),
            session_record,
            "question",
            UUID(int=1),
        )
    ]

    assert ("error", {"code": "generation_truncated"}) in events
    assert ("done", {"finish": "stop", "actions": [], "degraded": True}) in events
    assert len(records) == 1
    assert records[0].status == "partial"
    assert records[0].error_class == "output_token_limit"
    assert records[0].tokens_out == MAX_OUTPUT_TOKENS
    assert records[0].max_output_tokens == MAX_OUTPUT_TOKENS
    assert records[0].finish_reason == "length"
