from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_scope
from app.db.models import AuditLog, ErrorEvent, LLMCall, Setting
from app.db.session import get_db_session
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
                "trace_id": row.trace_id,
                "model": row.model,
                "provider": row.provider,
                "status": row.status,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "max_output_tokens": row.max_output_tokens,
                "finish_reason": row.finish_reason,
            }
            for row in rows
        ]
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
    before = dict(setting.value) if setting is not None else None
    if setting is None:
        setting = Setting(key=key, value=body.value, updated_by=principal.name)
        session.add(setting)
    else:
        setting.value = body.value
        setting.updated_by = principal.name
    session.add(
        AuditLog(
            actor=principal.name,
            action="settings.patch",
            target=key,
            before=before,
            after=body.value,
            trace_id=request.state.trace_id,
        )
    )
    await session.commit()
    return {"key": key, "before": before, "value": body.value}
