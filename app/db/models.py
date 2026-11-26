from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _assistant_table_args() -> dict[str, str]:
    return {"schema": "assistant"}


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = _assistant_table_args()

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = _assistant_table_args()

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column("before", JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column("after", JSONB)
    trace_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (
        Index("traces_started_at_idx", desc("started_at")),
        Index("traces_session_started_idx", "session_id", "started_at"),
        Index("traces_flags_idx", "flags", postgresql_using="gin"),
        {"schema": "assistant"},
    )

    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    ip_hash: Mapped[str | None] = mapped_column(Text)
    release_id: Mapped[int | None] = mapped_column(BigInteger)
    route: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int | None] = mapped_column(Integer)
    ttfw_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retrieved: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    link_map: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    user_text: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prompt_sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    flags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    feedback: Mapped[str | None] = mapped_column(Text)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Span(Base):
    __tablename__ = "spans"
    __table_args__ = (
        Index("spans_trace_id_idx", "trace_id"),
        {"schema": "assistant"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    span_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class ErrorEvent(Base):
    __tablename__ = "error_events"
    __table_args__ = _assistant_table_args()

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trace_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    level: Mapped[str | None] = mapped_column(Text)
    component: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    exc: Mapped[str | None] = mapped_column(Text)
    ctx: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = _assistant_table_args()

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    ua_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    turn_count: Mapped[int | None] = mapped_column(Integer, server_default=sql_text("0"))
    state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = _assistant_table_args()

    doc_key: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url_path: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assistant.sources.id")
    )
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql_text("'{}'")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'active'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = _assistant_table_args()

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    last_payload_hash: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("chunks_chunk_key_idx", "chunk_key"),
        Index("chunks_content_hash_idx", "content_hash"),
        UniqueConstraint("chunk_key", "version"),
        {"schema": "assistant"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    chunk_key: Mapped[str] = mapped_column(Text, nullable=False)
    doc_key: Mapped[str] = mapped_column(
        Text, ForeignKey("assistant.documents.doc_key"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    overrides_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assistant.chunks.id")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embed_text: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_via: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("link_key", "version"),
        {"schema": "assistant"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    link_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql_text("'{}'")
    )
    doc_key: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("50"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("true"))
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Suppression(Base):
    __tablename__ = "suppressions"
    __table_args__ = _assistant_table_args()

    chunk_key: Mapped[str] = mapped_column(Text, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (
        Index(
            "one_open_draft",
            "status",
            unique=True,
            postgresql_where=sql_text("status = 'draft'"),
        ),
        {"schema": "assistant"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("assistant.releases.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    eval_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReleaseChunk(Base):
    __tablename__ = "release_chunks"
    __table_args__ = _assistant_table_args()

    release_id: Mapped[int] = mapped_column(
        ForeignKey("assistant.releases.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("assistant.chunks.id"), primary_key=True)


class ReleaseLink(Base):
    __tablename__ = "release_links"
    __table_args__ = _assistant_table_args()

    release_id: Mapped[int] = mapped_column(
        ForeignKey("assistant.releases.id", ondelete="CASCADE"), primary_key=True
    )
    link_id: Mapped[UUID] = mapped_column(ForeignKey("assistant.links.id"), primary_key=True)


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = _assistant_table_args()

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index(
            "one_running_ingestion",
            "status",
            unique=True,
            postgresql_where=sql_text("status = 'running'"),
        ),
        {"schema": "assistant"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(Text)
    release_id: Mapped[int | None] = mapped_column(BigInteger)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"
    __table_args__ = _assistant_table_args()

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistant.ingestion_runs.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    doc_key: Mapped[str | None] = mapped_column(Text)
    chunk_key: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("idempotency_records_expires_at_idx", "expires_at"),
        {"schema": "assistant"},
    )

    key_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assistant.api_keys.id", ondelete="CASCADE")
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvaluationCase(Base):
    __tablename__ = "eval_cases"
    __table_args__ = _assistant_table_args()

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    history: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expect: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    created_from_trace: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    active: Mapped[bool | None] = mapped_column(Boolean, server_default=sql_text("true"))


class EvaluationRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = _assistant_table_args()

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    release_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("llm_calls_started_at_idx", desc("started_at")),
        Index("llm_calls_model_started_idx", "model", desc("started_at")),
        {"schema": "assistant"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttfw_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    est_tokens_in: Mapped[int | None] = mapped_column(Integer)
    reserved_out: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    remaining: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retry_after_s: Mapped[int | None] = mapped_column(Integer)
