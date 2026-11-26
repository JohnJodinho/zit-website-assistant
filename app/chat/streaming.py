from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from itertools import pairwise
from time import monotonic
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.answer import answer_is_grounded
from app.chat.cache import AnswerCache
from app.chat.generation import AttemptFailure, Generation, begin_generation
from app.chat.providers import ProviderError, ProviderUpdate, Usage
from app.chat.quota import QuotaManager
from app.chat.retrieval import ChatPlan, prepare_chat_plan
from app.chat.runtime import get_providers
from app.config import Settings
from app.content.snapshot import ContentSnapshot
from app.db.models import LLMCall, SessionRecord
from app.obs.logging import get_logger

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CAPACITY_ANSWER = "Please contact ZIT Admissions for help with this question."


async def stream_chat(
    request: Request,
    session: AsyncSession,
    session_record: SessionRecord,
    question: str,
    trace_id: UUID,
) -> AsyncIterator[tuple[str, dict[str, object]]]:
    settings: Settings = request.app.state.settings
    snapshot: ContentSnapshot | None = request.app.state.active_snapshot
    plan_task = asyncio.create_task(prepare_chat_plan(request, question, snapshot))
    try:
        async for _ in _wait_with_pings(request, plan_task):
            yield "ping", {}
        plan = plan_task.result()
    except ClientDisconnected:
        await _update_session(session, session_record)
        return
    except asyncio.CancelledError:
        await _cancel_task(plan_task)
        await _update_session(session, session_record)
        raise
    cache: AnswerCache = request.app.state.answer_cache
    cached = None
    if plan.answer is None and snapshot is not None:
        cached = cache.get(
            question,
            snapshot.release_id,
        )
        if cached is not None and not answer_is_grounded(cached.answer, plan.hits, plan.links):
            cached = None
    yield (
        "meta",
        _meta(
            plan,
            trace_id,
            snapshot,
            path=cached.path if cached is not None else None,
        ),
    )
    if cached is not None:
        yield "delta", {"t": cached.answer}
        yield "done", {"finish": "stop", "actions": [], "degraded": False}
        await _update_session(session, session_record)
        return
    if plan.answer is not None:
        yield "delta", {"t": plan.answer}
        yield "done", {"finish": "stop", "actions": [], "degraded": plan.degraded}
        await _update_session(session, session_record)
        return

    quota: QuotaManager = request.app.state.quota_manager
    generation_task = asyncio.create_task(
        begin_generation(
            settings,
            get_providers(request),
            quota,
            plan.prompt or "",
        )
    )
    try:
        async for _ in _wait_with_pings(request, generation_task):
            yield "ping", {}
        generation, failures = generation_task.result()
    except ClientDisconnected:
        await _update_session(session, session_record)
        return
    except asyncio.CancelledError:
        await _cancel_task(generation_task)
        await _update_session(session, session_record)
        raise
    await _record_failures(request, trace_id, failures)
    if generation is None:
        yield "meta", _meta(plan, trace_id, snapshot, path="capacity")
        yield "delta", {"t": _CAPACITY_ANSWER}
        yield "done", {"finish": "stop", "actions": [], "degraded": True}
        await _update_session(session, session_record)
        return

    text_buffer = generation.first_text
    full_answer = ""
    emitted = False
    invalid_answer = False
    try:
        async for event in _provider_events(request, generation):
            if event is None:
                yield "ping", {}
                continue
            part, update = event
            if update is not None:
                if update.usage is not None:
                    generation.usage = update.usage
                if update.finish_reason is not None:
                    generation.finish_reason = update.finish_reason
            if not part:
                continue
            text_buffer += part
            text_buffer, sent = _emit_complete_sentences(text_buffer)
            for sentence in sent:
                if not answer_is_grounded(sentence, plan.hits, plan.links):
                    invalid_answer = True
                    break
                emitted = True
                sentence_text = sentence + " "
                full_answer += sentence_text
                yield "delta", {"t": sentence_text}
            if invalid_answer:
                break
        output_limited = _output_limit_reached(generation)
        if invalid_answer:
            if emitted:
                yield (
                    "error",
                    {
                        "code": (
                            "generation_truncated" if output_limited else "answer_validation_failed"
                        )
                    },
                )
                yield "done", {"finish": "stop", "actions": [], "degraded": True}
            else:
                yield "delta", {"t": _CAPACITY_ANSWER}
                yield "done", {"finish": "stop", "actions": [], "degraded": True}
        else:
            tail = text_buffer.strip()
            if tail and answer_is_grounded(tail, plan.hits, plan.links):
                emitted = True
                full_answer += tail
                yield "delta", {"t": tail}
            elif tail:
                invalid_answer = True
            if invalid_answer and emitted:
                yield (
                    "error",
                    {
                        "code": (
                            "generation_truncated" if output_limited else "answer_validation_failed"
                        )
                    },
                )
                yield "done", {"finish": "stop", "actions": [], "degraded": True}
            elif invalid_answer or not emitted:
                yield "delta", {"t": _CAPACITY_ANSWER}
                yield "done", {"finish": "stop", "actions": [], "degraded": True}
            elif output_limited:
                yield "error", {"code": "generation_truncated"}
                yield "done", {"finish": "stop", "actions": [], "degraded": True}
            else:
                if snapshot is not None:
                    cache.put(
                        question,
                        full_answer,
                        snapshot.release_id,
                        settings.session_cache_seconds,
                    )
                yield "done", {"finish": "stop", "actions": [], "degraded": False}
        _correct_quota(quota, generation)
        quota.record_success(generation.model_id)
        if output_limited:
            status, error_class = "partial", "output_token_limit"
        elif invalid_answer:
            status, error_class = "error", "answer_validation_failed"
        else:
            status, error_class = "ok", None
        await _record_generation(
            request,
            trace_id,
            generation,
            status,
            error_class,
        )
    except ClientDisconnected:
        _correct_quota(quota, generation)
        await _record_generation(request, trace_id, generation, "cancelled", "client_disconnected")
        return
    except asyncio.CancelledError:
        _correct_quota(quota, generation)
        await _record_generation(request, trace_id, generation, "cancelled", "request_cancelled")
        raise
    except (ProviderError, TimeoutError) as exc:
        quota.record_failure(
            generation.model_id,
            settings.breaker_min_open_s,
            settings.breaker_failures,
        )
        _correct_quota(quota, generation)
        await _record_generation(request, trace_id, generation, "partial", type(exc).__name__)
        if emitted:
            yield "error", {"code": "partial_generation_failed"}
            yield "done", {"finish": "stop", "actions": [], "degraded": True}
        else:
            yield "delta", {"t": _CAPACITY_ANSWER}
            yield "done", {"finish": "stop", "actions": [], "degraded": True}
    finally:
        await generation.stream.aclose()
        await _update_session(session, session_record)


async def _provider_events(
    request: Request,
    generation: Generation,
) -> AsyncIterator[tuple[str, ProviderUpdate | None] | None]:
    next_ping = monotonic() + request.app.state.settings.sse_ping_seconds
    while True:
        task = asyncio.create_task(anext(generation.stream))
        while not task.done():
            timeout = min(0.1, max(0.0, next_ping - monotonic()))
            await asyncio.wait({task}, timeout=timeout)
            if await request.is_disconnected():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                raise ClientDisconnected
            if monotonic() >= next_ping:
                yield None
                next_ping = monotonic() + request.app.state.settings.sse_ping_seconds
        try:
            yield task.result()
        except StopAsyncIteration:
            return


def _output_limit_reached(generation: Generation) -> bool:
    if generation.finish_reason is not None and generation.finish_reason.casefold() in {
        "length",
        "max_tokens",
    }:
        return True
    return (
        generation.usage is not None and generation.usage.tokens_out >= generation.max_output_tokens
    )


async def _wait_with_pings(
    request: Request,
    task: asyncio.Task[object],
) -> AsyncIterator[None]:
    next_ping = monotonic() + request.app.state.settings.sse_ping_seconds
    while not task.done():
        timeout = min(0.1, max(0.0, next_ping - monotonic()))
        await asyncio.wait({task}, timeout=timeout)
        if await request.is_disconnected():
            await _cancel_task(task)
            raise ClientDisconnected
        if monotonic() >= next_ping:
            yield None
            next_ping = monotonic() + request.app.state.settings.sse_ping_seconds


async def _cancel_task(task: asyncio.Task[object]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _emit_complete_sentences(text: str) -> tuple[str, list[str]]:
    matches = list(_SENTENCE.finditer(text))
    if not matches:
        return text, []
    sentences = [text[: matches[0].start() + 1].strip()]
    sentences.extend(
        text[previous.end() : match.start() + 1].strip() for previous, match in pairwise(matches)
    )
    remaining = text[matches[-1].end() :]
    return remaining, [sentence for sentence in sentences if sentence]


def _meta(
    plan: ChatPlan,
    trace_id: UUID,
    snapshot: ContentSnapshot | None,
    *,
    path: str | None = None,
) -> dict[str, object]:
    return {
        "request_id": str(trace_id),
        "release": snapshot.release_id if snapshot is not None else None,
        "path": path or plan.path,
        "intent": list(plan.intent),
        "links": {link.link_key: {"label": link.label, "url": link.url} for link in plan.links},
        "degraded": plan.degraded,
    }


def _correct_quota(quota: QuotaManager, generation: Generation) -> None:
    if generation.usage is not None:
        quota.correct(
            generation.model_id,
            generation.reserved_tokens,
            generation.usage.tokens_in + generation.usage.tokens_out,
        )


async def _record_failures(
    request: Request,
    trace_id: UUID,
    failures: list[AttemptFailure],
) -> None:
    records = [
        _llm_call(
            trace_id,
            failure.provider,
            failure.model_id,
            failure.tier,
            failure.started_at,
            failure.duration_ms,
            "error",
            failure.error_class,
            failure.status_code,
            None,
            None,
            failure.estimated_input_tokens,
            failure.reserved_tokens,
            failure.max_output_tokens,
            failure.finish_reason,
        )
        for failure in failures
    ]
    await _persist_llm_calls(request, records)


async def _record_generation(
    request: Request,
    trace_id: UUID,
    generation: Generation,
    status: str,
    error_class: str | None = None,
) -> None:
    usage = generation.usage
    record = _llm_call(
        trace_id,
        generation.provider,
        generation.model_id,
        generation.tier,
        generation.started_at,
        int((monotonic() - generation.started_clock) * 1000),
        status,
        error_class,
        None,
        generation.ttfw_ms,
        usage,
        generation.estimated_input_tokens,
        generation.reserved_tokens,
        generation.max_output_tokens,
        generation.finish_reason,
    )
    await _persist_llm_calls(request, [record])


def _llm_call(
    trace_id: UUID,
    provider: str,
    model: str,
    tier: int,
    started_at: datetime,
    duration_ms: int,
    status: str,
    error_class: str | None,
    status_code: int | None,
    ttfw_ms: int | None,
    usage: Usage | None,
    estimated_input_tokens: int,
    reserved_tokens: int,
    max_output_tokens: int,
    finish_reason: str | None,
) -> LLMCall:
    return LLMCall(
        trace_id=trace_id,
        provider=provider,
        model=model,
        tier=tier,
        started_at=started_at,
        duration_ms=duration_ms,
        status=status,
        error_class=error_class,
        http_status=status_code,
        ttfw_ms=ttfw_ms,
        tokens_in=usage.tokens_in if usage else None,
        tokens_out=usage.tokens_out if usage else None,
        est_tokens_in=estimated_input_tokens,
        reserved_out=max(0, reserved_tokens - estimated_input_tokens),
        max_output_tokens=max_output_tokens,
        finish_reason=finish_reason,
    )


async def _persist_llm_calls(request: Request, records: list[LLMCall]) -> None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if not records or session_factory is None:
        return
    try:
        async with session_factory() as session:
            session.add_all(records)
            await session.commit()
    except SQLAlchemyError as exc:
        get_logger("chat.telemetry", request.app.state.settings).error(
            "llm_call_persist_failed",
            error_type=type(exc).__name__,
        )


async def _update_session(session: AsyncSession, record: SessionRecord) -> None:
    record.turn_count = (record.turn_count or 0) + 1
    record.last_seen_at = datetime.now(UTC)
    try:
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise


class ClientDisconnected(Exception):
    pass
