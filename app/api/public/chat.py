from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chat.pii import mask_pii
from app.chat.sessions import create_session_token

router = APIRouter(prefix="/api/v1", tags=["chat"])


class SessionRequest(BaseModel):
    turnstile_token: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_token: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int = Field(ge=-1, le=1)


@router.get("/config")
async def public_config(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    rollout = max(0, min(100, settings.rollout_percent))
    return {
        "enabled": not settings.kill_switch,
        "rollout_percent": rollout,
        "maintenance_message": settings.maintenance_message,
        "privacy_notice": "Do not enter personal or confidential information.",
    }


@router.post("/sessions")
async def create_session(body: SessionRequest, request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    if settings.kill_switch:
        raise HTTPException(status_code=503, detail="maintenance")
    token = create_session_token()
    return {
        "session_token": token,
        "expires_in_minutes": settings.session_ttl_minutes,
    }


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> StreamingResponse:
    settings = request.app.state.settings
    if settings.kill_switch:
        raise HTTPException(status_code=503, detail="maintenance")
    if len(body.message) > settings.message_max_chars:
        raise HTTPException(status_code=413, detail="message_too_long")
    _masked, found = mask_pii(body.message)
    trace_id = getattr(request.state, "trace_id", x_request_id or "")

    async def stream() -> AsyncIterator[bytes]:
        yield _sse(
            "meta",
            {
                "request_id": str(trace_id),
                "release": getattr(request.app.state.active_snapshot, "release_id", None),
                "path": "capacity",
                "links": {},
            },
        )
        answer = (
            "ZIT Admissions can help with course, fee, duration, and application questions. "
            "Please contact admissions for the latest details."
        )
        if found:
            answer = (
                "I can help with ZIT course information. Please continue without personal details."
            )
        yield _sse("delta", {"t": answer})
        yield _sse(
            "done",
            {
                "finish": "stop",
                "actions": [],
                "degraded": True,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": str(trace_id),
        },
    )


@router.post("/feedback")
async def feedback(body: FeedbackRequest, request: Request) -> dict[str, str]:
    del request
    return {"status": "recorded", "trace_id": body.trace_id}


@router.post("/client-events")
async def client_events(request: Request) -> dict[str, str]:
    del request
    return {"status": "accepted"}


def _sse(event: str, data: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
