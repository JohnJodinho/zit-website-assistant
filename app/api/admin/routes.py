from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_scope
from app.db.models import ApiKey, AuditLog, Span, Trace
from app.db.session import get_db_session
from app.security.keys import (
    ALL_ADMIN_SCOPES,
    AdminPrincipal,
    AdminScope,
    generate_admin_key,
)

router = APIRouter(prefix="/admin/v1", tags=["admin"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("API-key name cannot be blank")
        return normalized

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        invalid = set(values) - set(ALL_ADMIN_SCOPES)
        if invalid:
            raise ValueError("Unknown API-key scope")
        if len(values) != len(set(values)):
            raise ValueError("Scopes must be unique")
        return values


class ApiKeyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.KEYS))],
) -> dict[str, object]:
    raw_key, key_hash = generate_admin_key()
    api_key = ApiKey(name=body.name, key_hash=key_hash, scopes=body.scopes)
    session.add(api_key)
    session.add(
        AuditLog(
            actor=principal.name,
            action="api_key.create",
            target=body.name,
            before=None,
            after={"name": body.name, "scopes": body.scopes},
            trace_id=request.state.trace_id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="api_key_name_exists") from exc

    return {"key": raw_key, "api_key": ApiKeyView.model_validate(api_key)}


@router.get("/api-keys")
async def list_api_keys(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.KEYS))],
    limit: int = Query(default=50, ge=1, le=100),
    before_id: UUID | None = None,
) -> dict[str, object]:
    query = select(ApiKey).order_by(ApiKey.id.desc()).limit(limit + 1)
    if before_id is not None:
        query = query.where(ApiKey.id < before_id)
    rows = (await session.scalars(query)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [ApiKeyView.model_validate(row) for row in page],
        "next_cursor": str(page[-1].id) if has_more and page else None,
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.KEYS))],
) -> dict[str, str]:
    api_key = await session.get(ApiKey, key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="api_key_not_found")
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(UTC)
        session.add(
            AuditLog(
                actor=principal.name,
                action="api_key.revoke",
                target=api_key.name,
                before={"revoked": False},
                after={"revoked": True},
                trace_id=request.state.trace_id,
            )
        )
        await session.commit()
    return {"status": "revoked"}


@router.get("/traces/{trace_id}")
async def get_trace(
    trace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    trace = await session.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace_not_found")
    spans = (
        await session.scalars(select(Span).where(Span.trace_id == trace_id).order_by(Span.id.asc()))
    ).all()
    return {
        "trace": {
            "trace_id": trace.trace_id,
            "kind": trace.kind,
            "started_at": trace.started_at,
            "duration_ms": trace.duration_ms,
            "status": trace.status,
            "error_code": trace.error_code,
            "route": trace.route,
        },
        "spans": [
            {
                "span_id": span.span_id,
                "parent_id": span.parent_id,
                "name": span.name,
                "started_at": span.started_at,
                "duration_ms": span.duration_ms,
                "status": span.status,
                "attrs": span.attrs,
                "error": span.error,
            }
            for span in spans
        ],
    }


@router.get("/traces")
async def list_traces(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_trace_id: UUID | None = None,
) -> dict[str, object]:
    query = select(Trace).order_by(Trace.started_at.desc(), Trace.trace_id.desc())
    if before_trace_id is not None:
        cursor = await session.get(Trace, before_trace_id)
        if cursor is None:
            raise HTTPException(status_code=404, detail="trace_cursor_not_found")
        query = query.where(
            or_(
                Trace.started_at < cursor.started_at,
                and_(
                    Trace.started_at == cursor.started_at,
                    Trace.trace_id < cursor.trace_id,
                ),
            )
        )
    rows = (await session.scalars(query.limit(limit + 1))).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [
            {
                "trace_id": row.trace_id,
                "kind": row.kind,
                "started_at": row.started_at,
                "duration_ms": row.duration_ms,
                "status": row.status,
                "error_code": row.error_code,
                "route": row.route,
            }
            for row in page
        ],
        "next_cursor": str(page[-1].trace_id) if has_more and page else None,
    }


@router.get("/audit")
async def list_audit_records(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    rows = (await session.scalars(query)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "at": row.at,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "before": row.before,
                "after": row.after,
                "trace_id": row.trace_id,
            }
            for row in page
        ],
        "next_cursor": page[-1].id if has_more and page else None,
    }
