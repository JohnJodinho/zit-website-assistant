from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.limits import SlidingWindowLimiter
from app.chat.pii import mask_pii
from app.chat.session_store import create_session_record, find_session, rate_limit_key
from app.chat.streaming import stream_chat
from app.chat.turnstile import TurnstileUnavailable, verify_turnstile
from app.db.models import Span, Trace
from app.db.session import get_db_session
from app.obs.logging import get_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])


class SessionRequest(BaseModel):
    turnstile_token: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_token: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: UUID
    session_token: str = Field(min_length=40, max_length=48)
    rating: int = Field(ge=-1, le=1)


class ClientEventRequest(BaseModel):
    trace_id: UUID
    session_token: str = Field(min_length=40, max_length=48)
    event: Literal["response_error", "feedback_submitted"]


@router.get("/config")
async def public_config(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    rollout = max(0, min(100, settings.rollout_percent))
    return {
        "enabled": not settings.kill_switch and rollout > 0,
        "rollout_percent": rollout,
        "maintenance_message": settings.maintenance_message,
        "privacy_notice": "Do not enter personal or confidential information.",
    }


@router.post("/sessions")
async def create_session(
    body: SessionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    settings = request.app.state.settings
    _require_rollout(request)
    try:
        client_key = rate_limit_key(request, settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    limiter: SlidingWindowLimiter = request.app.state.session_rate_limiter
    if not limiter.allow(
        client_key,
        limit=settings.session_rate_limit_per_minute,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="session_rate_limited")
    if settings.turnstile_enabled:
        turnstile_token = body.turnstile_token
        if not turnstile_token or len(turnstile_token) > 2048:
            raise HTTPException(status_code=403, detail="turnstile_verification_failed")
        if settings.turnstile_secret is None:
            raise HTTPException(status_code=503, detail="turnstile_not_configured")
        try:
            verified = await verify_turnstile(
                turnstile_token,
                settings.turnstile_secret.get_secret_value(),
            )
        except TurnstileUnavailable as exc:
            fail_open_limiter: SlidingWindowLimiter = request.app.state.turnstile_fail_open_limiter
            if not fail_open_limiter.allow(
                client_key,
                limit=settings.turnstile_fail_open_per_minute,
                window_seconds=60,
            ):
                raise HTTPException(
                    status_code=503,
                    detail="turnstile_temporarily_unavailable",
                ) from exc
            get_logger("chat.turnstile").warning("turnstile_fail_open_allowed")
        else:
            if not verified:
                raise HTTPException(status_code=403, detail="turnstile_verification_failed")
    try:
        token = await create_session_record(session, settings, request)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    return {
        "session_token": token,
        "expires_in_minutes": settings.session_ttl_minutes,
    }


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    settings = request.app.state.settings
    _require_rollout(request)
    if len(body.message) > settings.message_max_chars:
        raise HTTPException(status_code=413, detail="message_too_long")
    if not body.session_token:
        raise HTTPException(status_code=401, detail="session_required")
    try:
        session_record = await find_session(session, settings, body.session_token)
        client_key = (
            session_record.ip_hash
            if session_record and session_record.ip_hash
            else rate_limit_key(request, settings)
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    if session_record is None:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    request.state.session_id = session_record.id
    limiter: SlidingWindowLimiter = request.app.state.chat_rate_limiter
    if not limiter.allow(
        client_key,
        limit=settings.chat_rate_limit_per_minute,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="chat_rate_limited")
    active_sessions: set[UUID] = request.app.state.active_sessions
    if session_record.id in active_sessions:
        raise HTTPException(status_code=409, detail="session_request_in_progress")
    active_sessions.add(session_record.id)
    masked, _found = mask_pii(body.message)
    trace_id = getattr(request.state, "trace_id", uuid4())

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event, payload in stream_chat(
                request,
                session,
                session_record,
                masked,
                trace_id,
            ):
                yield _sse(event, payload)
        finally:
            active_sessions.discard(session_record.id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": str(trace_id),
        },
    )


def _require_rollout(request: Request) -> None:
    settings = request.app.state.settings
    if settings.kill_switch or settings.rollout_percent <= 0:
        raise HTTPException(status_code=503, detail="assistant_not_available")
    if settings.rollout_percent >= 100:
        return
    try:
        key = rate_limit_key(request, settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 100
    if bucket >= settings.rollout_percent:
        raise HTTPException(status_code=503, detail="assistant_not_in_rollout")


@router.post("/feedback")
async def feedback(
    body: FeedbackRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    settings = request.app.state.settings
    try:
        session_record = await find_session(session, settings, body.session_token)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    if session_record is None:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    limiter: SlidingWindowLimiter = request.app.state.chat_rate_limiter
    if not limiter.allow(
        session_record.ip_hash or "unknown",
        limit=settings.chat_rate_limit_per_minute,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="chat_rate_limited")
    trace = await _find_trace(session, request, body.trace_id)
    if trace is None or trace.session_id != session_record.id:
        raise HTTPException(status_code=404, detail="trace_not_found")
    trace.feedback = str(body.rating)
    await session.commit()
    return {"status": "recorded", "trace_id": str(body.trace_id)}


@router.post("/client-events")
async def client_events(
    body: ClientEventRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    settings = request.app.state.settings
    try:
        session_record = await find_session(session, settings, body.session_token)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="session_service_not_configured") from exc
    if session_record is None:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    limiter: SlidingWindowLimiter = request.app.state.chat_rate_limiter
    if not limiter.allow(
        session_record.ip_hash or "unknown",
        limit=settings.chat_rate_limit_per_minute,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="chat_rate_limited")
    trace = await _find_trace(session, request, body.trace_id)
    if trace is None or trace.session_id != session_record.id:
        raise HTTPException(status_code=404, detail="trace_not_found")
    session.add(
        Span(
            trace_id=body.trace_id,
            span_id=uuid4().hex[:16],
            parent_id=None,
            name=f"widget.{body.event}",
            started_at=datetime.now(UTC),
            duration_ms=0,
            status="ok",
            attrs={"event": body.event},
            error=None,
        )
    )
    await session.commit()
    return {"status": "recorded"}


def _sse(event: str, data: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def _find_trace(
    session: AsyncSession,
    request: Request,
    trace_id: UUID,
) -> Trace | None:
    trace = await session.get(Trace, trace_id)
    if trace is not None:
        return trace
    writer = getattr(request.app.state, "telemetry_writer", None)
    if writer is not None:
        await writer.flush_once()
    return await session.get(Trace, trace_id)
