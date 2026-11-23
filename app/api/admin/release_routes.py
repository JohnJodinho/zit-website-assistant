from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_scope
from app.content.idempotency import execute_idempotently
from app.content.repository import (
    active_release_id,
    add_audit_record,
    release_chunks,
    release_links,
)
from app.content.snapshot import load_release_snapshot, validate_release_content
from app.db.models import Chunk, Link, Release, ReleaseChunk, ReleaseLink
from app.db.session import get_db_session
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["releases"])


@router.get("/releases")
async def list_releases(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="invalid_page_limit")
    query = select(Release).order_by(Release.id.desc())
    if before_id is not None:
        query = query.where(Release.id < before_id)
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [_release_view(release) for release in page],
        "next_cursor": page[-1].id if len(rows) > limit and page else None,
    }


@router.get("/releases/current-draft")
async def get_current_draft(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    draft = await session.scalar(select(Release).where(Release.status == "draft"))
    if draft is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return _release_view(draft)


@router.get("/releases/{release_id}/diff")
async def get_release_diff(
    release_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    release = await session.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release_not_found")
    current_chunks = await release_chunks(session, release_id)
    current_links = await release_links(session, release_id)
    parent_chunks = (
        await release_chunks(session, release.parent_id) if release.parent_id is not None else {}
    )
    parent_links = (
        await release_links(session, release.parent_id) if release.parent_id is not None else {}
    )
    return {
        "release_id": release_id,
        "parent_id": release.parent_id,
        "chunks": _diff_keys(parent_chunks, current_chunks, lambda chunk: chunk.content_hash),
        "links": _diff_keys(parent_links, current_links, lambda link: link.url),
    }


@router.post("/releases/{release_id}/evaluate")
async def evaluate_release(
    release_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    settings = request.app.state.settings

    async def mutation() -> dict[str, object]:
        release = await session.get(Release, release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        chunks, links = await _release_records(session, release_id)
        check = validate_release_content(chunks, links, settings)
        report: dict[str, object] = {
            "data_check": {
                "valid": check.valid,
                "errors": list(check.errors),
                "warnings": list(check.warnings),
            },
            "search_tests": {"available": False, "reason": "phase_3_not_implemented"},
            "publishable": False,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
        release.eval_report = report
        add_audit_record(
            session,
            actor=principal.name,
            action="release.evaluate",
            target=str(release_id),
            before=None,
            after=report,
            trace_id=request.state.trace_id,
        )
        return report

    return await execute_idempotently(
        session,
        request,
        principal,
        {"release_id": release_id, "action": "evaluate"},
        mutation,
    )


@router.post("/releases/{release_id}/publish")
async def publish_release(
    release_id: int,
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    raise HTTPException(status_code=409, detail="search_evaluation_unavailable")


@router.post("/releases/{release_id}/rollback")
async def rollback_release(
    release_id: int,
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    raise HTTPException(status_code=409, detail="search_evaluation_unavailable")


@router.post("/releases/current-draft/discard")
async def discard_current_draft(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        draft = await session.scalar(select(Release).where(Release.status == "draft"))
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        before = {"status": draft.status}
        draft.status = "archived"
        add_audit_record(
            session,
            actor=principal.name,
            action="release.discard",
            target=str(draft.id),
            before=before,
            after={"status": "archived"},
            trace_id=request.state.trace_id,
        )
        return {"release_id": draft.id, "status": draft.status}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"action": "discard_current_draft"},
        mutation,
    )


@router.post("/snapshot/reload")
async def reload_snapshot(
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    session_factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    try:
        async with session_factory() as session:
            release_id = await active_release_id(session)
            if release_id is None:
                raise HTTPException(status_code=409, detail="no_published_release")
            candidate = await load_release_snapshot(
                session,
                release_id,
                request.app.state.settings,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="snapshot_validation_failed") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    request.app.state.active_snapshot = candidate
    request.app.state.snapshot_error = None
    return {
        "status": "loaded",
        "release_id": candidate.release_id,
        "chunks": len(candidate.chunks),
        "links": len(candidate.links),
    }


async def _release_records(
    session: AsyncSession,
    release_id: int,
) -> tuple[list[Chunk], list[Link]]:
    chunks = (
        await session.scalars(
            select(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
    ).all()
    links = (
        await session.scalars(
            select(Link)
            .join(ReleaseLink, ReleaseLink.link_id == Link.id)
            .where(ReleaseLink.release_id == release_id)
        )
    ).all()
    return list(chunks), list(links)


def _diff_keys[Value](
    before: Mapping[str, Value],
    after: Mapping[str, Value],
    value: Callable[[Value], object],
) -> dict[str, list[str]]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        key for key in set(before) & set(after) if value(before[key]) != value(after[key])
    )
    unchanged = sorted((set(before) & set(after)) - set(changed))
    return {"added": added, "changed": changed, "removed": removed, "unchanged": unchanged}


def _release_view(release: Release) -> dict[str, object]:
    return {
        "id": release.id,
        "status": release.status,
        "parent_id": release.parent_id,
        "note": release.note,
        "created_by": release.created_by,
        "created_at": release.created_at,
        "published_at": release.published_at,
        "stats": release.stats,
        "eval_report": release.eval_report,
    }
