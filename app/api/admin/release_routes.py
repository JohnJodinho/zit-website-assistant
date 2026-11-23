from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_embedding_client, require_scope
from app.config import Settings
from app.content.idempotency import (
    execute_idempotently,
    execute_idempotently_outside_transaction,
)
from app.content.repository import (
    active_release_id,
    add_audit_record,
    release_chunks,
    release_links,
)
from app.content.snapshot import (
    ContentSnapshot,
    SnapshotChunk,
    SnapshotLink,
    load_release_snapshot,
    validate_release_content,
)
from app.db.models import Chunk, EvaluationCase, Link, Release, ReleaseChunk, ReleaseLink, Setting
from app.db.session import get_db_session
from app.embeddings.client import BgeEmbeddingClient
from app.search.evaluation import Evaluator
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
    embedding_client = get_embedding_client(request)

    async def mutation() -> dict[str, object]:
        release = await session.get(Release, release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        chunks, links = await _release_records(session, release_id)
        check = validate_release_content(chunks, links, settings)
        content_hash = _release_content_hash(chunks, links)
        search_report: dict[str, object] = {"available": False, "reason": "no_eval_cases"}
        if check.valid:
            cases = (
                await session.scalars(select(EvaluationCase).where(EvaluationCase.active.is_(True)))
            ).all()
            if cases:
                snapshot = await load_release_snapshot_for_evaluation(
                    session,
                    release_id,
                    settings,
                    chunks,
                    links,
                )
                search_report = await _evaluate_search_cases(
                    session,
                    cases,
                    snapshot,
                    embedding_client,
                    settings,
                )
                current_chunks, current_links = await _release_records(session, release_id)
                if _release_content_hash(current_chunks, current_links) != content_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="release_changed_during_evaluation",
                    )
        report: dict[str, object] = {
            "data_check": {
                "valid": check.valid,
                "errors": list(check.errors),
                "warnings": list(check.warnings),
            },
            "content_hash": content_hash,
            "search_tests": search_report,
            "publishable": check.valid and bool(search_report.get("valid", False)),
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
        await session.commit()
        return report

    return await execute_idempotently_outside_transaction(
        session,
        request,
        principal,
        {"release_id": release_id, "action": "evaluate"},
        mutation,
    )


async def _evaluate_search_cases(
    session: AsyncSession,
    cases: Sequence[EvaluationCase],
    snapshot: ContentSnapshot,
    embedding_client: BgeEmbeddingClient,
    settings: Settings,
) -> dict[str, object]:
    missing = [case for case in cases if case.embedding is None or len(case.embedding) != 768]
    await session.commit()
    if missing:
        vectors = await embedding_client.embed_texts(
            [case.question for case in missing],
            input_type="query",
        )
        for case, vector in zip(missing, vectors, strict=True):
            case.embedding = vector
    if any(case.embedding is None for case in cases):
        raise RuntimeError("Evaluation query embeddings are incomplete")
    query_vectors = {
        case.question: tuple(float(value) for value in case.embedding or ()) for case in cases
    }
    evaluation_report = await Evaluator().evaluate(
        session,
        snapshot,
        query_vectors,
        retrieval_min_hit=settings.gate_retrieval_min_hit,
        link_min_hit=0.95,
        off_topic_min_refusal=0.95,
        wrong_refusal_max=0.05,
        vector_min=settings.gate_vector_min,
        bm25_min=settings.gate_bm25_min,
    )
    return {
        "available": True,
        "valid": evaluation_report.valid,
        "retrieval_hit_rate": evaluation_report.retrieval_hit_rate,
        "link_hit_rate": evaluation_report.link_hit_rate,
        "off_topic_refusal_rate": evaluation_report.off_topic_refusal_rate,
        "wrong_refusal_rate": evaluation_report.wrong_refusal_rate,
        "details": evaluation_report.details,
    }


@router.post("/releases/{release_id}/publish")
async def publish_release(
    release_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        release = await session.get(Release, release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        if release.status == "published":
            raise HTTPException(status_code=409, detail="release_already_published")
        if not release.status == "draft":
            raise HTTPException(status_code=409, detail="release_not_draft")
        report = release.eval_report
        if not isinstance(report, dict) or report.get("publishable") is not True:
            raise HTTPException(status_code=409, detail="release_evaluation_required")
        chunks, links = await _release_records(session, release_id)
        if report.get("content_hash") != _release_content_hash(chunks, links):
            raise HTTPException(status_code=409, detail="release_changed_after_evaluation")

        previous_id = await active_release_id(session)
        now = datetime.now(UTC)
        release.status = "published"
        release.published_at = now
        await session.execute(
            update(Setting)
            .where(Setting.key == "active_release_id")
            .values(value={"value": release_id}, updated_by=principal.name)
        )
        active_setting = await session.get(Setting, "active_release_id")
        if active_setting is None:
            session.add(
                Setting(
                    key="active_release_id",
                    value={"value": release_id},
                    updated_by=principal.name,
                )
            )
        add_audit_record(
            session,
            actor=principal.name,
            action="release.publish",
            target=str(release_id),
            before={"active_release_id": previous_id},
            after={"active_release_id": release_id},
            trace_id=request.state.trace_id,
        )
        await session.flush()
        candidate = await load_release_snapshot(
            session,
            release_id,
            request.app.state.settings,
        )
        request.app.state.active_snapshot = candidate
        request.app.state.snapshot_error = None
        return {
            "status": "published",
            "release_id": release_id,
            "previous_release_id": previous_id,
            "eval_report": report,
        }

    return await execute_idempotently(
        session,
        request,
        principal,
        {"release_id": release_id, "action": "publish"},
        mutation,
    )


@router.post("/releases/{release_id}/rollback")
async def rollback_release(
    release_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.PUBLISH))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        release = await session.get(Release, release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        if release.status != "published":
            raise HTTPException(status_code=409, detail="rollback_target_not_published")
        current_id = await active_release_id(session)
        if release_id == current_id:
            raise HTTPException(status_code=409, detail="release_already_active")
        await session.execute(
            update(Setting)
            .where(Setting.key == "active_release_id")
            .values(value={"value": release_id}, updated_by=principal.name)
        )
        active_setting = await session.get(Setting, "active_release_id")
        if active_setting is None:
            session.add(
                Setting(
                    key="active_release_id",
                    value={"value": release_id},
                    updated_by=principal.name,
                )
            )
        add_audit_record(
            session,
            actor=principal.name,
            action="release.rollback",
            target=str(release_id),
            before={"active_release_id": current_id},
            after={"active_release_id": release_id},
            trace_id=request.state.trace_id,
        )
        await session.flush()
        candidate = await load_release_snapshot(
            session,
            release_id,
            request.app.state.settings,
        )
        request.app.state.active_snapshot = candidate
        request.app.state.snapshot_error = None
        return {"status": "rolled_back", "release_id": release_id}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"release_id": release_id, "action": "rollback"},
        mutation,
    )


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


def _release_content_hash(chunks: list[Chunk], links: list[Link]) -> str:
    content = {
        "chunks": sorted(
            (
                chunk.chunk_key,
                chunk.content_hash,
                chunk.embedding_model,
                chunk.metadata_json,
            )
            for chunk in chunks
        ),
        "links": sorted((link.link_key, link.label, link.url, link.active) for link in links),
    }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def load_release_snapshot_for_evaluation(
    session: AsyncSession,
    release_id: int,
    settings: object,
    chunks: list[Chunk],
    links: list[Link],
) -> ContentSnapshot:
    del session, settings
    snapshot_chunks = tuple(
        SnapshotChunk(
            id=str(chunk.id),
            chunk_key=chunk.chunk_key,
            doc_key=chunk.doc_key,
            kind=chunk.kind,
            text=chunk.text,
            embed_text=chunk.embed_text,
            token_count=chunk.token_count,
            metadata=dict(chunk.metadata_json),
            embedding=tuple(float(value) for value in (chunk.embedding or [])),
        )
        for chunk in chunks
    )
    snapshot_links = tuple(
        SnapshotLink(
            link_key=link.link_key,
            kind=link.kind,
            label=link.label,
            url=link.url,
            description=link.description,
            aliases=tuple(link.aliases),
            priority=link.priority,
        )
        for link in links
        if link.active
    )
    return ContentSnapshot(
        release_id=release_id,
        chunks=snapshot_chunks,
        links=snapshot_links,
        loaded_at=datetime.now(UTC).isoformat(),
    )


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
