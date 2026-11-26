from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch
from uuid import UUID

from app.chat.providers import ProviderError, ProviderUpdate, Usage
from app.chat.quota import QuotaManager
from app.chat.retrieval import ChatPlan
from app.chat.sessions import hash_session_token
from app.config import Settings, get_settings
from app.content.snapshot import ContentSnapshot
from app.db.models import (
    Chunk,
    ErrorEvent,
    LLMCall,
    Release,
    ReleaseChunk,
    SessionRecord,
    Setting,
    Span,
    Trace,
)
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.search.hybrid import SearchHit
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MARKER = "zzdrill-chat-db"
_MODEL = "zzdrill-chat-db-fake"


class DrillFailure(RuntimeError):
    pass


class FakeProvider:
    def __init__(self) -> None:
        self.fail_next = False

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> AsyncGenerator[tuple[str, ProviderUpdate | None], None]:
        del model, prompt, max_output_tokens
        if self.fail_next:
            self.fail_next = False
            yield "", ProviderUpdate(usage=Usage(7, 0))
            raise ProviderError(_MARKER, 503)
        yield "The retrieved ZIT answer is supported.", None
        yield "", ProviderUpdate(usage=Usage(14, 5))


async def fake_plan(
    request: Any,
    question: str,
    snapshot: ContentSnapshot | None,
) -> ChatPlan:
    del request, question
    if snapshot is None:
        raise DrillFailure("active_snapshot_missing")
    hit = SearchHit(
        chunk_key=f"{_MARKER}:chunk",
        doc_key=f"{_MARKER}:document",
        score=1.0,
        text="The retrieved ZIT answer is supported.",
        vector_score=1.0,
        bm25_score=1.0,
    )
    return ChatPlan(
        path="retrieval",
        intent=("drill",),
        answer=None,
        prompt="Answer using the marked drill context.",
        links=(),
        hits=(hit,),
        degraded=False,
        confidence={"vector": 1.0, "bm25": 1.0},
    )


async def read_release_baseline(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int]:
    async with factory() as session:
        setting = await session.get(Setting, "active_release_id")
        if setting is None or type(setting.value.get("value")) is not int:
            raise DrillFailure("active_release_missing")
        release_id = setting.value["value"]
        release = await session.get(Release, release_id)
        if release is None or release.status != "published":
            raise DrillFailure("active_release_not_published")
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
        drill_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(
                ReleaseChunk.release_id == release_id,
                Chunk.doc_key.startswith("zzdrill-"),
            )
        )
        return release_id, int(chunk_count or 0), int(drill_count or 0)


async def tag_session(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str,
) -> UUID:
    if settings.session_pepper is None:
        raise DrillFailure("session_pepper_missing")
    token_hash = hash_session_token(
        token,
        settings.session_pepper.get_secret_value(),
    )
    async with factory() as session:
        record = await session.scalar(
            select(SessionRecord).where(SessionRecord.token_hash == token_hash)
        )
        if record is None:
            raise DrillFailure("session_not_persisted")
        record.state = {"label": _MARKER}
        await session.commit()
        return record.id


async def tag_trace(
    factory: async_sessionmaker[AsyncSession],
    trace_id: UUID,
) -> bool:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        async with factory() as session:
            trace = await session.get(Trace, trace_id)
            if trace is not None:
                trace.flags = [_MARKER]
                await session.commit()
                return True
        await asyncio.sleep(0.1)
    return False


async def cleanup(
    factory: async_sessionmaker[AsyncSession],
    session_id: UUID | None,
    trace_ids: set[UUID],
) -> bool:
    async with factory() as session:
        if trace_ids:
            await session.execute(delete(Span).where(Span.trace_id.in_(trace_ids)))
            await session.execute(delete(ErrorEvent).where(ErrorEvent.trace_id.in_(trace_ids)))
            await session.execute(delete(LLMCall).where(LLMCall.trace_id.in_(trace_ids)))
            await session.execute(delete(Trace).where(Trace.trace_id.in_(trace_ids)))
        if session_id is not None:
            await session.execute(delete(SessionRecord).where(SessionRecord.id == session_id))
        await session.commit()
    async with factory() as session:
        remaining_traces = (
            await session.scalar(
                select(func.count()).select_from(Trace).where(Trace.trace_id.in_(trace_ids))
            )
            if trace_ids
            else 0
        )
        remaining_calls = (
            await session.scalar(
                select(func.count()).select_from(LLMCall).where(LLMCall.trace_id.in_(trace_ids))
            )
            if trace_ids
            else 0
        )
        remaining_session = (
            await session.get(SessionRecord, session_id) if session_id is not None else None
        )
        return not remaining_traces and not remaining_calls and remaining_session is None


def _trace_id(response: Any) -> UUID:
    value = response.headers.get("X-Request-ID")
    if not value:
        raise DrillFailure("request_id_missing")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DrillFailure("request_id_missing") from exc


def _daily_tokens(quota: QuotaManager, model: str) -> int:
    counter = quota._counters.get(model)
    return sum(count for _, count in counter.daily_tokens) if counter is not None else 0


def main() -> int:
    base_settings = get_settings()
    if base_settings.database_url is None:
        print("CHAT-DB FAIL\tDATABASE_URL missing")
        return 1
    secret = SecretStr(secrets.token_urlsafe(48))
    models = json.dumps(
        [
            {
                "model": _MODEL,
                "provider": "zzdrill",
                "tier": 1,
                "enabled": True,
                "free_confirmed": True,
                "rpm": 30,
                "rpd": 1000,
                "tpm": 8000,
                "tpd": 200000,
            }
        ]
    )
    settings = base_settings.model_copy(
        update={
            "session_pepper": secret,
            "rollout_percent": 100,
            "kill_switch": False,
            "turnstile_enabled": False,
            "llm_models": models,
            "llm_max_attempts": 1,
        }
    )
    audit_engine = create_database_engine(settings)
    if audit_engine is None:
        print("CHAT-DB FAIL\tDATABASE_URL missing")
        return 1
    audit_factory = create_session_factory(audit_engine)
    audit_loop = asyncio.new_event_loop()
    trace_ids: set[UUID] = set()
    session_id: UUID | None = None
    baseline: tuple[int, int, int] | None = None
    failure: str | None = None
    try:
        baseline = audit_loop.run_until_complete(read_release_baseline(audit_factory))
        if baseline[2] != 0:
            raise DrillFailure("active_release_contains_drill_content")
        application = create_app(settings)
        provider = FakeProvider()
        with (
            patch("app.chat.streaming.prepare_chat_plan", fake_plan),
            TestClient(application) as client,
        ):
            if application.state.active_snapshot is None:
                raise DrillFailure("application_snapshot_missing")
            if application.state.active_snapshot.release_id != baseline[0]:
                raise DrillFailure("snapshot_release_mismatch")
            application.state.chat_providers = {"zzdrill": provider}

            session_response = client.post("/api/v1/sessions", json={})
            trace_ids.add(_trace_id(session_response))
            if session_response.status_code != 200:
                raise DrillFailure("session_creation_failed")
            token = session_response.json().get("session_token")
            if not isinstance(token, str):
                raise DrillFailure("session_token_missing")
            session_id = audit_loop.run_until_complete(tag_session(audit_factory, settings, token))
            session_trace_tagged = audit_loop.run_until_complete(
                tag_trace(audit_factory, _trace_id(session_response))
            )
            if not session_trace_tagged:
                raise DrillFailure("session_trace_not_persisted")

            chat_response = client.post(
                "/api/v1/chat/stream",
                json={"message": "Test this retrieved ZIT answer.", "session_token": token},
            )
            trace_id = _trace_id(chat_response)
            trace_ids.add(trace_id)
            if chat_response.status_code != 200 or "event: done" not in chat_response.text:
                raise DrillFailure("fake_chat_stream_failed")
            if not audit_loop.run_until_complete(tag_trace(audit_factory, trace_id)):
                raise DrillFailure("chat_trace_not_persisted")

            feedback_response = client.post(
                "/api/v1/feedback",
                json={"trace_id": str(trace_id), "session_token": token, "rating": 1},
            )
            trace_ids.add(_trace_id(feedback_response))
            if feedback_response.status_code != 200:
                raise DrillFailure("feedback_not_stored")
            if not audit_loop.run_until_complete(
                tag_trace(audit_factory, _trace_id(feedback_response))
            ):
                raise DrillFailure("feedback_trace_not_persisted")

            before_failed_call = _daily_tokens(application.state.quota_manager, _MODEL)
            provider.fail_next = True
            failed_response = client.post(
                "/api/v1/chat/stream",
                json={"message": "Run the marked failed-call check.", "session_token": token},
            )
            failed_trace_id = _trace_id(failed_response)
            trace_ids.add(failed_trace_id)
            if failed_response.status_code != 200:
                raise DrillFailure("failed_call_fallback_missing")
            corrected = _daily_tokens(application.state.quota_manager, _MODEL) - before_failed_call
            if corrected != 7:
                raise DrillFailure("failed_call_quota_not_corrected")
            if not audit_loop.run_until_complete(tag_trace(audit_factory, failed_trace_id)):
                raise DrillFailure("failed_call_trace_not_persisted")

        audit_loop.run_until_complete(_verify_records(audit_factory, session_id, trace_ids))
    except DrillFailure as exc:
        failure = str(exc)
    except Exception as exc:
        failure = type(exc).__name__
    finally:
        try:
            cleaned = audit_loop.run_until_complete(cleanup(audit_factory, session_id, trace_ids))
            after = audit_loop.run_until_complete(read_release_baseline(audit_factory))
            if not cleaned:
                failure = failure or "cleanup_incomplete"
            if baseline is not None and after != baseline:
                failure = failure or "release_changed"
        except Exception as exc:
            failure = failure or f"cleanup_{type(exc).__name__}"
        audit_loop.run_until_complete(audit_engine.dispose())
        audit_loop.close()

    if failure:
        print(f"CHAT-DB FAIL\t{failure}")
        return 1
    print("CHAT-DB PASS\tsession, trace, llm-call, feedback, quota correction, cleanup")
    return 0


async def _verify_records(
    factory: async_sessionmaker[AsyncSession],
    session_id: UUID,
    trace_ids: set[UUID],
) -> None:
    async with factory() as session:
        record = await session.get(SessionRecord, session_id)
        if record is None or record.state.get("label") != _MARKER:
            raise DrillFailure("session_marker_missing")
        traces = (await session.scalars(select(Trace).where(Trace.trace_id.in_(trace_ids)))).all()
        if len(traces) != len(trace_ids) or any(
            _MARKER not in (trace.flags or []) for trace in traces
        ):
            raise DrillFailure("trace_rows_missing_or_unmarked")
        chat_trace = next(
            (
                trace
                for trace in traces
                if trace.route == "/api/v1/chat/stream" and trace.session_id == session_id
            ),
            None,
        )
        if chat_trace is None or chat_trace.feedback != "1":
            raise DrillFailure("feedback_not_persisted")
        calls = (
            await session.scalars(
                select(LLMCall).where(
                    LLMCall.trace_id.in_(trace_ids),
                    LLMCall.model == _MODEL,
                )
            )
        ).all()
        if not any(call.status == "ok" for call in calls):
            raise DrillFailure("successful_llm_call_missing")
        if not any(call.status == "error" for call in calls):
            raise DrillFailure("failed_llm_call_missing")


if __name__ == "__main__":
    raise SystemExit(main())
