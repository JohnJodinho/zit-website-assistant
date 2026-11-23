from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_scope
from app.db.models import ErrorEvent, LLMCall, SessionRecord, Setting, Trace
from app.db.session import get_db_session
from app.notifications import SilentNotifier
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["operations"])


class SettingPatch(BaseModel):
    value: dict[str, object]


@router.get("/errors")
async def list_errors(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    rows = (
        await session.scalars(select(ErrorEvent).order_by(ErrorEvent.id.desc()).limit(50))
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "trace_id": row.trace_id,
                "code": row.code,
                "component": row.component,
                "at": row.at,
            }
            for row in rows
        ]
    }


@router.get("/llm-calls")
async def list_llm_calls(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    rows = (await session.scalars(select(LLMCall).order_by(LLMCall.id.desc()).limit(50))).all()
    return {
        "items": [
            {
                "id": row.id,
                "model": row.model,
                "provider": row.provider,
                "status": row.status,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
            }
            for row in rows
        ]
    }


@router.get("/metrics/summary")
async def metrics_summary(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    trace_count = await session.scalar(select(func.count()).select_from(Trace))
    llm_count = await session.scalar(select(func.count()).select_from(LLMCall))
    error_count = await session.scalar(select(func.count()).select_from(ErrorEvent))
    return {
        "traces": trace_count or 0,
        "llm_calls": llm_count or 0,
        "errors": error_count or 0,
    }


@router.get("/settings")
async def get_settings(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    rows = (await session.scalars(select(Setting).order_by(Setting.key.asc()))).all()
    return {"items": [{"key": row.key, "value": row.value} for row in rows]}


@router.patch("/settings/{key}")
async def patch_setting(
    key: str,
    body: SettingPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    allowed = {"KILL_SWITCH", "ROLLOUT_PERCENT", "MAINTENANCE_MESSAGE"}
    if key not in allowed:
        raise HTTPException(status_code=422, detail="live_setting_not_allowed")
    setting = await session.get(Setting, key)
    before = setting.value if setting is not None else None
    if setting is None:
        setting = Setting(key=key, value=body.value, updated_by=principal.name)
        session.add(setting)
    else:
        setting.value = body.value
        setting.updated_by = principal.name
    await session.flush()
    return {"key": key, "before": before, "value": body.value}


@router.post("/cache/purge")
async def purge_cache(
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    del request
    return {"status": "purged"}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    from uuid import UUID

    try:
        parsed = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_session_id") from exc
    await session.execute(delete(SessionRecord).where(SessionRecord.id == parsed))
    return {"status": "deleted"}


@router.post("/alerts/test")
async def test_alert(
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    await SilentNotifier().publish("ZIT assistant test alert")
    del principal
    return {"status": "noop"}
