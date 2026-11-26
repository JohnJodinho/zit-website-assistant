from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from app.chat.models import eligible_models
from app.chat.providers import ProviderError, ProviderUpdate, StreamingProvider, Usage
from app.chat.quota import QuotaManager
from app.config import Settings

MAX_OUTPUT_TOKENS = 600


@dataclass(frozen=True, slots=True)
class AttemptFailure:
    model_id: str
    provider: str
    tier: int
    error_class: str
    status_code: int | None
    started_at: datetime
    duration_ms: int
    reserved_tokens: int
    estimated_input_tokens: int
    max_output_tokens: int
    finish_reason: str | None


@dataclass(slots=True)
class Generation:
    model_id: str
    provider: str
    tier: int
    stream: AsyncGenerator[tuple[str, ProviderUpdate | None], None]
    first_text: str
    usage: Usage | None
    finish_reason: str | None
    max_output_tokens: int
    started_at: datetime
    started_clock: float
    ttfw_ms: int
    reserved_tokens: int
    estimated_input_tokens: int


async def begin_generation(
    settings: Settings,
    providers: Mapping[str, StreamingProvider],
    quota: QuotaManager,
    prompt: str,
) -> tuple[Generation | None, list[AttemptFailure]]:
    models = eligible_models(settings.llm_models)[: settings.llm_max_attempts]
    deadline = monotonic() + settings.llm_pretoken_deadline_s
    reserved_input = _estimate_tokens(prompt)
    reserved_tokens = reserved_input + MAX_OUTPUT_TOKENS
    failures: list[AttemptFailure] = []

    for model in models:
        provider = providers.get(model.provider)
        if provider is None or not quota.eligible(
            model.model_id,
            rpm=model.rpm,
            rpd=model.rpd,
            tpm=model.tpm,
            tpd=model.tpd,
            reserve_tokens=reserved_tokens,
            minute_safety=settings.quota_safety_per_minute,
            daily_safety=settings.quota_safety_daily,
        ):
            continue

        quota.reserve(model.model_id, reserved_tokens)
        started_at = datetime.now(UTC)
        started_clock = monotonic()
        usage: Usage | None = None
        finish_reason: str | None = None
        stream = provider.stream(
            model=model.model_id,
            prompt=prompt,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        try:
            while True:
                remaining = min(
                    deadline - monotonic(),
                    settings.llm_first_token_timeout_s,
                )
                if remaining <= 0:
                    raise TimeoutError("first_token_deadline")
                text, update = await asyncio.wait_for(anext(stream), timeout=remaining)
                if update is not None:
                    if update.usage is not None:
                        usage = update.usage
                    if update.finish_reason is not None:
                        finish_reason = update.finish_reason
                if text:
                    return (
                        Generation(
                            model_id=model.model_id,
                            provider=model.provider,
                            tier=model.tier,
                            stream=stream,
                            first_text=text,
                            usage=usage,
                            finish_reason=finish_reason,
                            max_output_tokens=MAX_OUTPUT_TOKENS,
                            started_at=started_at,
                            started_clock=started_clock,
                            ttfw_ms=int((monotonic() - started_clock) * 1000),
                            reserved_tokens=reserved_tokens,
                            estimated_input_tokens=reserved_input,
                        ),
                        failures,
                    )
        except asyncio.CancelledError:
            if usage is not None:
                quota.correct(
                    model.model_id,
                    reserved_tokens,
                    usage.tokens_in + usage.tokens_out,
                )
            await stream.aclose()
            raise
        except (ProviderError, TimeoutError, StopAsyncIteration) as exc:
            error_class = exc.error_class if isinstance(exc, ProviderError) else type(exc).__name__
            status_code = exc.status_code if isinstance(exc, ProviderError) else None
            quota.record_failure(
                model.model_id,
                settings.breaker_min_open_s,
                settings.breaker_failures,
            )
            if usage is not None:
                quota.correct(
                    model.model_id,
                    reserved_tokens,
                    usage.tokens_in + usage.tokens_out,
                )
            failures.append(
                AttemptFailure(
                    model_id=model.model_id,
                    provider=model.provider,
                    tier=model.tier,
                    error_class=error_class,
                    status_code=status_code,
                    started_at=started_at,
                    duration_ms=int((monotonic() - started_clock) * 1000),
                    reserved_tokens=reserved_tokens,
                    estimated_input_tokens=reserved_input,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    finish_reason=finish_reason,
                )
            )
            await stream.aclose()
            if monotonic() >= deadline:
                break

    return None, failures


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
