from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.obs.logging import get_logger
from app.obs.writer import TelemetryWriter

router = APIRouter(prefix="/api/v1", tags=["health"])
_MIGRATION_HEAD = "0002_phase2_content"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    database_ready, migration_ready = await _database_readiness(request.app.state.engine)
    writer: TelemetryWriter | None = request.app.state.telemetry_writer
    snapshot = getattr(request.app.state, "active_snapshot", None)
    snapshot_error = getattr(request.app.state, "snapshot_error", None)
    ready = database_ready and migration_ready and snapshot_error is None
    return JSONResponse(
        status_code=200 if ready else 503,
        content=_readiness_body(
            database_ready,
            migration_ready,
            writer,
            snapshot,
            snapshot_error,
        ),
    )


async def _database_readiness(engine: AsyncEngine | None) -> tuple[bool, bool]:
    if engine is None:
        return False, False
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            return True, await _migration_is_ready(connection)
    except SQLAlchemyError as exc:
        get_logger("readiness").warning(
            "database_unavailable",
            error_type=type(exc).__name__,
        )
        return False, False


async def _migration_is_ready(connection: AsyncConnection) -> bool:
    try:
        result = await connection.execute(text("SELECT version_num FROM public.alembic_version"))
    except SQLAlchemyError as exc:
        get_logger("readiness").warning(
            "migration_state_unavailable",
            error_type=type(exc).__name__,
        )
        return False
    return result.scalar_one_or_none() == _MIGRATION_HEAD


def _readiness_body(
    database_ready: bool,
    migration_ready: bool,
    writer: TelemetryWriter | None,
    snapshot: object | None,
    snapshot_error: str | None,
) -> dict[str, Any]:
    ready = database_ready and migration_ready and snapshot_error is None
    return {
        "status": "ready" if ready else "not_ready",
        "database": "ready" if database_ready else "unavailable",
        "migration": "ready" if migration_ready else "not_ready",
        "telemetry": {
            "queue_size": writer.queue_size if writer else 0,
            "dropped_spans": writer.dropped_spans if writer else 0,
            "dropped_traces": writer.dropped_traces if writer else 0,
            "dropped_errors": writer.dropped_errors if writer else 0,
        },
        "release": "loaded" if snapshot is not None else "not_loaded",
        "snapshot_error": snapshot_error,
    }
