from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.obs.writer import TelemetryWriter, make_error_record, make_span_record, make_trace_record
from sqlalchemy.exc import SQLAlchemyError


def make_records() -> tuple[dict[str, object], dict[str, object]]:
    trace_id = uuid4()
    started_at = datetime.now(UTC)
    trace = make_trace_record(trace_id, started_at, 5, 200, "/api/v1/health")
    span = make_span_record(trace_id, uuid4().hex[:16], started_at, 5, 200, "/api/v1/health")
    return trace, span


async def test_writer_flushes_trace_and_span_batch() -> None:
    persisted: list[
        tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]
    ] = []

    async def persist(traces, spans, errors) -> None:
        persisted.append((traces, spans, errors))

    writer = TelemetryWriter(max_items=4, persist_function=persist)
    trace, span = make_records()
    await writer.enqueue(trace, span)

    written = await writer.flush_once()

    assert written == 2
    assert persisted[0][0] == [trace]
    assert persisted[0][1] == [span]
    assert persisted[0][2] == []
    assert writer.queue_size == 0


async def test_writer_drops_spans_before_traces_when_queue_is_full() -> None:
    writer = TelemetryWriter(max_items=2, persist_function=_persist_nothing)
    first_trace, first_span = make_records()
    second_trace, second_span = make_records()

    assert await writer.enqueue(first_trace, first_span)
    assert await writer.enqueue(second_trace, second_span)

    assert writer.queue_size == 2
    assert len(writer._traces) == 2
    assert not writer._spans
    assert writer.dropped_spans == 2
    assert writer.dropped_traces == 0


async def test_writer_requeues_batch_after_database_failure() -> None:
    async def fail_to_persist(traces, spans, errors) -> None:
        raise SQLAlchemyError("database unavailable")

    writer = TelemetryWriter(max_items=3, persist_function=fail_to_persist)
    trace, span = make_records()
    await writer.enqueue(trace, span)

    assert await writer.flush_once() == 0
    assert writer.queue_size == 2
    assert writer.persist_failures == 1


async def test_writer_persists_safe_error_events() -> None:
    persisted_errors: list[dict[str, object]] = []

    async def persist(traces, spans, errors) -> None:
        persisted_errors.extend(errors)

    writer = TelemetryWriter(max_items=3, persist_function=persist)
    trace, span = make_records()
    error = make_error_record(trace["trace_id"], "/api/v1/health")
    await writer.enqueue(trace, span, error)

    await writer.flush_once()

    assert persisted_errors == [error]
    assert "message body" not in str(error)


async def test_writer_shutdown_flushes_queued_items() -> None:
    persisted_count = 0

    async def persist(traces, spans, errors) -> None:
        nonlocal persisted_count
        persisted_count += len(traces) + len(spans) + len(errors)

    writer = TelemetryWriter(max_items=5, persist_function=persist, flush_seconds=0.01)
    writer.start()
    trace, span = make_records()
    await writer.enqueue(trace, span)

    await writer.close(timeout=1)

    assert persisted_count == 2
    assert writer.queue_size == 0


async def _persist_nothing(traces, spans, errors) -> None:
    return None
