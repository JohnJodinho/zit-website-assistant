from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ErrorEvent, Span, Trace
from app.obs.logging import get_logger

JsonRecord = dict[str, Any]
PersistFunction = Callable[[list[JsonRecord], list[JsonRecord], list[JsonRecord]], Awaitable[None]]


@dataclass(slots=True)
class TelemetryWriter:
    session_factory: async_sessionmaker[AsyncSession] | None = None
    max_items: int = 5000
    batch_size: int = 100
    flush_seconds: float = 1.0
    persist_function: PersistFunction | None = None
    _traces: deque[JsonRecord] = field(init=False)
    _spans: deque[JsonRecord] = field(init=False)
    _errors: deque[JsonRecord] = field(init=False)
    _condition: asyncio.Condition = field(init=False)
    _stopping: bool = field(init=False, default=False)
    _stop_deadline: float | None = field(init=False, default=None)
    _task: asyncio.Task[None] | None = field(init=False, default=None)
    dropped_spans: int = field(init=False, default=0)
    dropped_traces: int = field(init=False, default=0)
    dropped_errors: int = field(init=False, default=0)
    persist_failures: int = field(init=False, default=0)
    logger: Any = field(init=False)

    def __post_init__(self) -> None:
        if self.max_items < 1:
            raise ValueError("max_items must be positive")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._traces: deque[JsonRecord] = deque()
        self._spans: deque[JsonRecord] = deque()
        self._errors: deque[JsonRecord] = deque()
        self._condition = asyncio.Condition()
        self.logger = get_logger("telemetry.writer")

    @property
    def queue_size(self) -> int:
        return len(self._traces) + len(self._spans) + len(self._errors)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Telemetry writer has already been started")
        self._task = asyncio.create_task(self._run(), name="telemetry-writer")

    async def enqueue(
        self,
        trace: JsonRecord,
        span: JsonRecord,
        error: JsonRecord | None = None,
    ) -> bool:
        async with self._condition:
            required_items = 1 + int(error is not None) + 1
            while self.queue_size + required_items > self.max_items and self._spans:
                self._spans.popleft()
                self.dropped_spans += 1

            keep_span = self.queue_size + required_items <= self.max_items
            if not keep_span:
                self.dropped_spans += 1
                required_items -= 1

            if self.queue_size + required_items > self.max_items:
                if error is not None and self.queue_size < self.max_items:
                    self._errors.append(error)
                    self._condition.notify()
                    self.dropped_traces += 1
                    return False
                self.dropped_traces += 1
                return False

            self._traces.append(trace)
            if keep_span:
                self._spans.append(span)
            if error is not None:
                self._errors.append(error)
            self._condition.notify()
            return True

    async def close(self, timeout: float = 10.0) -> None:
        if self._task is None:
            return
        async with self._condition:
            self._stopping = True
            self._stop_deadline = monotonic() + timeout
            self._condition.notify_all()
        try:
            await asyncio.wait_for(self._task, timeout=timeout + 1)
        except TimeoutError:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def flush_once(self) -> int:
        async with self._condition:
            traces = [
                self._traces.popleft() for _ in range(min(self.batch_size, len(self._traces)))
            ]
            remaining = max(self.batch_size - len(traces), 0)
            errors = [self._errors.popleft() for _ in range(min(remaining, len(self._errors)))]
            remaining -= len(errors)
            spans = [self._spans.popleft() for _ in range(min(remaining, len(self._spans)))]

        if not traces and not spans and not errors:
            return 0

        try:
            await self._persist(traces, spans, errors)
        except SQLAlchemyError as exc:
            self.persist_failures += 1
            await self._restore(traces, spans, errors)
            self.logger.error(
                "telemetry_persist_failed",
                error_type=type(exc).__name__,
                queued_items=self.queue_size,
            )
            return 0
        return len(traces) + len(spans) + len(errors)

    async def _persist(
        self,
        traces: list[JsonRecord],
        spans: list[JsonRecord],
        errors: list[JsonRecord],
    ) -> None:
        if self.persist_function is not None:
            await self.persist_function(traces, spans, errors)
            return
        if self.session_factory is None:
            raise RuntimeError("Telemetry persistence requires a session factory")

        async with self.session_factory() as session, session.begin():
            session.add_all(Trace(**record) for record in traces)
            await session.flush()
            session.add_all(Span(**record) for record in spans)
            session.add_all(ErrorEvent(**record) for record in errors)

    async def _restore(
        self,
        traces: list[JsonRecord],
        spans: list[JsonRecord],
        errors: list[JsonRecord],
    ) -> None:
        async with self._condition:
            while (
                self.queue_size + len(traces) + len(spans) + len(errors) > self.max_items
                and self._spans
            ):
                self._spans.pop()
                self.dropped_spans += 1
            while (
                spans and self.queue_size + len(traces) + len(spans) + len(errors) > self.max_items
            ):
                spans.pop()
                self.dropped_spans += 1
            while (
                traces and self.queue_size + len(traces) + len(spans) + len(errors) > self.max_items
            ):
                traces.pop()
                self.dropped_traces += 1
            while (
                errors and self.queue_size + len(traces) + len(spans) + len(errors) > self.max_items
            ):
                errors.pop()
                self.dropped_errors += 1
            self._traces.extendleft(reversed(traces))
            self._spans.extendleft(reversed(spans))
            self._errors.extendleft(reversed(errors))
            self._condition.notify()

    async def _run(self) -> None:
        while await self._wait_for_work():
            await self.flush_once()
            if self._shutdown_flush_expired():
                await self._discard_pending_at_shutdown()
                return
            if self.persist_failures:
                await asyncio.sleep(self.flush_seconds)

    async def _wait_for_work(self) -> bool:
        async with self._condition:
            if self._stopping and not self.queue_size:
                return False
            if self.queue_size or self._stopping:
                return True
            with suppress(TimeoutError):
                await asyncio.wait_for(self._condition.wait(), timeout=self.flush_seconds)
        return True

    def _shutdown_flush_expired(self) -> bool:
        return bool(
            self._stopping
            and self._stop_deadline is not None
            and monotonic() >= self._stop_deadline
            and self.queue_size
        )

    async def _discard_pending_at_shutdown(self) -> None:
        self.logger.error(
            "telemetry_shutdown_flush_expired",
            queued_items=self.queue_size,
            dropped_spans=self.dropped_spans,
            dropped_traces=self.dropped_traces,
            dropped_errors=self.dropped_errors,
        )
        async with self._condition:
            self._traces.clear()
            self._spans.clear()
            self._errors.clear()


def make_trace_record(
    trace_id: UUID,
    started_at: datetime,
    duration_ms: int,
    status_code: int,
    route: str,
) -> JsonRecord:
    return {
        "trace_id": trace_id,
        "kind": "admin" if route.startswith("/admin") else "client",
        "started_at": started_at,
        "duration_ms": duration_ms,
        "status": "ok" if status_code < 400 else "error",
        "error_code": None if status_code < 400 else f"http_{status_code}",
        "route": route,
    }


def make_span_record(
    trace_id: UUID,
    span_id: str,
    started_at: datetime,
    duration_ms: int,
    status_code: int,
    route: str,
) -> JsonRecord:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_id": None,
        "name": "http.request",
        "started_at": started_at,
        "duration_ms": duration_ms,
        "status": "ok" if status_code < 400 else "error",
        "attrs": {"route": route, "http.status_code": status_code},
        "error": None if status_code < 500 else "unhandled_error",
    }


def make_error_record(trace_id: UUID, route: str) -> JsonRecord:
    return {
        "trace_id": trace_id,
        "level": "ERROR",
        "component": "api",
        "code": "http_500",
        "message": "Request failed",
        "exc": None,
        "ctx": {"route": route},
    }
