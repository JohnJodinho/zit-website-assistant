from __future__ import annotations

import asyncio

import scripts.live_provider_check as live_check
from app.chat.models import LLMModel
from app.chat.providers import ProviderError, Usage


class FakeProvider:
    def __init__(
        self,
        events: tuple[tuple[str, Usage | None], ...],
        error: ProviderError | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.closed = False

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ):
        assert model == "test-model"
        assert prompt == live_check._PROMPT
        assert max_output_tokens == 80
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True


def _model() -> LLMModel:
    return LLMModel(
        model_id="test-model",
        provider="groq",
        tier=1,
        enabled=True,
        free_confirmed=True,
        rpm=30,
        rpd=1000,
        tpm=8000,
        tpd=200000,
    )


def test_live_check_consumes_stream_and_checks_grounding_and_usage(monkeypatch) -> None:
    provider = FakeProvider(
        (
            ("Contact ZIT ", None),
            ("Admissions for current course information.", None),
            ("", Usage(12, 8)),
        )
    )
    monkeypatch.setattr(live_check, "_provider", lambda *_: provider)

    result, rate_limited = asyncio.run(live_check._run_check("groq", _model(), "not-printed"))

    assert result.status == "PASS"
    assert (result.tokens_in, result.tokens_out) == (12, 8)
    assert rate_limited is False
    assert provider.closed is True


def test_live_check_stops_on_rate_limit_and_closes_provider(monkeypatch) -> None:
    provider = FakeProvider((), ProviderError("RateLimitError", 429))
    monkeypatch.setattr(live_check, "_provider", lambda *_: provider)

    result, rate_limited = asyncio.run(live_check._run_check("groq", _model(), "not-printed"))

    assert result.status == "FAIL"
    assert result.error == "RateLimitError"
    assert result.rate_limited is True
    assert rate_limited is True
    assert provider.closed is True


def test_live_check_cache_round_trips_without_answer_or_credentials(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "live-check.json"
    monkeypatch.setattr(live_check, "_CACHE_PATH", cache_path)
    cache = {
        "prompt-hash": live_check.CheckResult(
            status="PASS",
            model="test-model",
            tokens_in=12,
            tokens_out=8,
        )
    }

    live_check._save_cache(cache)

    assert live_check._load_cache() == cache
    serialized = cache_path.read_text(encoding="utf-8")
    assert "Contact ZIT" not in serialized
    assert "not-printed" not in serialized
