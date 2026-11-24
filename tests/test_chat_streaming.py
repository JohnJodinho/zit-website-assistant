from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.chat.streaming import ClientDisconnected, _emit_complete_sentences, _provider_events


def test_complete_sentence_extraction_keeps_unfinished_tail() -> None:
    remaining, sentences = _emit_complete_sentences("One. Two! Tail")

    assert sentences == ["One.", "Two!"]
    assert remaining == "Tail"


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
