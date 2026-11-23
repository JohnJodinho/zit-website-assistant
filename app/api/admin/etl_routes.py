from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_embedding_client, require_scope
from app.config import Settings
from app.content.archive import materialize_crawl_archive
from app.content.idempotency import (
    execute_idempotently,
    execute_idempotently_outside_transaction,
)
from app.content.importer import (
    inspect_supporting_json,
    load_crawl_import,
    report_as_dict,
)
from app.content.staging import IngestionConflict, stage_crawl
from app.db.models import AuditLog, IngestionEvent, IngestionRun
from app.db.session import get_db_session
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["content ingestion"])


class ETLJSONRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["crawl_md"]
    mode: Literal["dry_run", "stage", "publish"] = "dry_run"
    archive_base64: str
    force: bool = False


async def _limited_body(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="upload_too_large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_content_length") from exc

    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > max_bytes:
            raise HTTPException(status_code=413, detail="upload_too_large")
        body.extend(part)
    return bytes(body)


def _decode_json_archive(payload: bytes, settings: Settings) -> ETLJSONRequest:
    try:
        body = json.loads(payload)
        request = ETLJSONRequest.model_validate(body)
        archive = base64.b64decode(request.archive_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="invalid_etl_json") from exc
    if len(archive) > settings.etl_max_zip_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="upload_too_large")
    return request.model_copy(update={"archive_base64": base64.b64encode(archive).decode("ascii")})


def _input_options(
    request: Request,
    payload: bytes,
    settings: Settings,
) -> tuple[str, str, bool, bytes]:
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    if content_type == "application/json":
        if len(payload) > settings.etl_max_json_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="upload_too_large")
        parsed = _decode_json_archive(payload, settings)
        archive = base64.b64decode(parsed.archive_base64, validate=True)
        return parsed.source, parsed.mode, parsed.force, archive
    if content_type not in {"application/zip", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="unsupported_etl_content_type")
    source = request.query_params.get("source", "crawl_md")
    mode = request.query_params.get("mode", "dry_run")
    force = request.query_params.get("force", "false").lower() == "true"
    if source != "crawl_md" or mode not in {"dry_run", "stage", "publish"}:
        raise HTTPException(status_code=422, detail="invalid_etl_options")
    return source, mode, force, payload


def _supporting_counts(root: Path) -> dict[str, int]:
    courses, website = _supporting_paths(root)
    return inspect_supporting_json(courses, website)


def _supporting_paths(root: Path) -> tuple[Path, Path]:
    candidates = (
        (root / "src" / "data" / "courses.json", root / "content" / "website-content.json"),
        (root / "courses.json", root / "website-content.json"),
    )
    for courses, website in candidates:
        if courses.is_file() and website.is_file():
            return courses, website
    raise ValueError("Crawl ZIP must include both approved supporting course JSON files")


@router.post("/etl/runs")
async def create_etl_run(
    request: Request,
    principal: Annotated[
        AdminPrincipal,
        Depends(require_scope(AdminScope.ETL_RUN)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    max_mb = (
        settings.etl_max_json_mb if content_type == "application/json" else settings.etl_max_zip_mb
    )
    max_bytes = max_mb * 1024 * 1024
    raw_payload = await _limited_body(request, max_bytes)
    _, mode, force, archive_payload = _input_options(request, raw_payload, settings)
    if mode == "publish":
        raise HTTPException(status_code=409, detail="search_evaluation_unavailable")
    if force and AdminScope.PUBLISH.value not in principal.scopes:
        raise HTTPException(status_code=403, detail="force_requires_publish_scope")

    try:
        with materialize_crawl_archive(archive_payload, settings) as root:
            courses_json, website_content_json = _supporting_paths(root)
            crawl = load_crawl_import(
                root,
                courses_json=courses_json,
                website_content_json=website_content_json,
            )
            supporting_counts = _supporting_counts(root)
            if mode == "dry_run":
                return {
                    "mode": "dry_run",
                    "database_written": False,
                    "embedding_requests_made": False,
                    "crawl": report_as_dict(crawl.report),
                    "payload_hash": crawl.payload_hash,
                    "supporting_website_data": supporting_counts,
                    "warnings": crawl.warnings,
                }

            session_factory: async_sessionmaker[AsyncSession] | None = (
                request.app.state.session_factory
            )
            if session_factory is None:
                raise HTTPException(status_code=503, detail="database_unavailable")
            embeddings = get_embedding_client(request)

            async def mutation() -> dict[str, object]:
                try:
                    return await stage_crawl(
                        session_factory,
                        crawl,
                        embeddings,
                        settings,
                        actor=principal.name,
                        trace_id=request.state.trace_id,
                        force=force,
                    )
                except IngestionConflict as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                except (ValueError, RuntimeError) as exc:
                    raise HTTPException(status_code=422, detail="etl_stage_failed") from exc

            return await execute_idempotently_outside_transaction(
                session,
                request,
                principal,
                {
                    "payload_hash": crawl.payload_hash,
                    "mode": mode,
                    "force": force,
                },
                mutation,
            )
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid_crawl_input") from exc


@router.get("/etl/runs")
async def list_etl_runs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_id: UUID | None = None,
) -> dict[str, object]:
    query = select(IngestionRun).order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
    if before_id is not None:
        cursor = await session.get(IngestionRun, before_id)
        if cursor is None:
            raise HTTPException(status_code=404, detail="ingestion_run_not_found")
        query = query.where(
            (IngestionRun.started_at < cursor.started_at)
            | ((IngestionRun.started_at == cursor.started_at) & (IngestionRun.id < cursor.id))
        )
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [_run_view(run) for run in page],
        "next_cursor": str(page[-1].id) if len(rows) > limit and page else None,
    }


@router.get("/etl/runs/{run_id}")
async def get_etl_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    run = await session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ingestion_run_not_found")
    events = (
        await session.scalars(
            select(IngestionEvent)
            .where(IngestionEvent.run_id == run_id)
            .order_by(IngestionEvent.id.asc())
        )
    ).all()
    return {
        **_run_view(run),
        "events": [
            {
                "id": event.id,
                "stage": event.stage,
                "doc_key": event.doc_key,
                "chunk_key": event.chunk_key,
                "action": event.action,
                "detail": event.detail,
                "at": event.at,
            }
            for event in events
        ],
    }


@router.post("/etl/runs/{run_id}/discard")
async def discard_etl_run(
    run_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.ETL_RUN))],
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        run = await session.get(IngestionRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ingestion_run_not_found")
        if run.status == "running":
            raise HTTPException(status_code=409, detail="ingestion_run_is_running")
        before = {"status": run.status}
        run.status = "discarded"
        session.add(
            AuditLog(
                actor=principal.name,
                action="etl.discard",
                target=str(run_id),
                before=before,
                after={"status": "discarded"},
                trace_id=request.state.trace_id,
            )
        )
        return {"status": "discarded"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"run_id": str(run_id), "action": "discard"},
        mutation,
    )


def _run_view(run: IngestionRun) -> dict[str, object]:
    return {
        "id": run.id,
        "source_kind": run.source_kind,
        "mode": run.mode,
        "status": run.status,
        "payload_hash": run.payload_hash,
        "release_id": run.release_id,
        "requested_by": run.requested_by,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "stats": run.stats,
        "warnings": run.warnings,
        "error": run.error,
        "trace_id": run.trace_id,
    }
