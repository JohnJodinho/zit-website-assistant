from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.config import Settings
from app.obs.logging import get_logger
from app.obs.writer import (
    TelemetryWriter,
    make_error_record,
    make_span_record,
    make_trace_record,
)


def request_context_middleware(
    settings: Settings,
) -> Callable[[Request, RequestResponseEndpoint], Awaitable[Response]]:
    async def middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        trace_id = uuid4()
        span_id = uuid4().hex[:16]
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        request.state.trace_id = trace_id
        bind_contextvars(trace_id=str(trace_id))
        response: Response | None = None

        try:
            response = await call_next(request)
            return response
        finally:
            try:
                status_code = response.status_code if response is not None else 500
                matched_route = request.scope.get("route")
                route = getattr(matched_route, "path", "unmatched")
                elapsed_ms = int((perf_counter() - started_clock) * 1000)
                if response is not None:
                    response.headers["X-Request-ID"] = str(trace_id)
                writer: TelemetryWriter | None = getattr(
                    request.app.state, "telemetry_writer", None
                )
                if writer is not None:
                    trace_record = make_trace_record(
                        trace_id,
                        started_at,
                        elapsed_ms,
                        status_code,
                        route,
                    )
                    session_id = getattr(request.state, "session_id", None)
                    if session_id is not None:
                        trace_record["session_id"] = session_id
                    await writer.enqueue(
                        trace_record,
                        make_span_record(
                            trace_id,
                            span_id,
                            started_at,
                            elapsed_ms,
                            status_code,
                            route,
                        ),
                        make_error_record(trace_id, route) if status_code >= 500 else None,
                    )
                get_logger("api.request", settings).info(
                    "request_complete",
                    method=request.method,
                    route=route,
                    status_code=status_code,
                    duration_ms=elapsed_ms,
                )
            finally:
                clear_contextvars()

    return middleware
