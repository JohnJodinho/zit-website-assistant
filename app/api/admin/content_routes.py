from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_scope
from app.content.idempotency import execute_idempotently
from app.content.models import ContentChunk
from app.content.provider import embed_documents
from app.content.repository import (
    active_release_id,
    add_audit_record,
    add_chunk_version,
    attach_chunk,
    ensure_draft,
    release_chunks,
    remove_chunk_from_release,
    validate_link_keys,
)
from app.content.schemas import ChunkCreate, ChunkPatch, DocumentCreate, DocumentPatch
from app.content.validation import ContentValidationError, build_manual_chunk
from app.db.models import Chunk, Document, Release, ReleaseChunk, Suppression
from app.db.session import get_db_session
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["content"])


@router.get("/documents")
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_key: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    query = select(Document).order_by(Document.doc_key.asc())
    if before_key is not None:
        query = query.where(Document.doc_key > before_key)
    if status_filter is not None:
        if status_filter not in {"active", "archived"}:
            raise HTTPException(status_code=422, detail="invalid_document_status")
        query = query.where(Document.status == status_filter)
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [_document_view(row) for row in page],
        "next_cursor": page[-1].doc_key if len(rows) > limit and page else None,
    }


@router.get("/documents/{doc_key}")
async def get_document(
    doc_key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    document = await session.get(Document, doc_key)
    if document is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    return _document_view(document)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(
    body: DocumentCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        if await session.get(Document, body.doc_key) is not None:
            raise HTTPException(status_code=409, detail="document_already_exists")
        document = Document(
            doc_key=body.doc_key,
            doc_type=body.doc_type,
            title=body.title.strip(),
            url_path=body.url_path,
            origin="manual",
            aliases=_unique_values(body.aliases),
            status="active",
        )
        session.add(document)
        add_audit_record(
            session,
            actor=principal.name,
            action="document.create",
            target=body.doc_key,
            before=None,
            after={"doc_type": body.doc_type, "title": body.title},
            trace_id=request.state.trace_id,
        )
        await session.flush()
        return _document_view(document)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json"),
        mutation,
    )


@router.patch("/documents/{doc_key}")
async def update_document(
    doc_key: str,
    body: DocumentPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        document = await session.get(Document, doc_key)
        if document is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        before = _document_view(document)
        _apply_document_patch(document, body)
        add_audit_record(
            session,
            actor=principal.name,
            action="document.update",
            target=doc_key,
            before=before,
            after=_document_view(document),
            trace_id=request.state.trace_id,
        )
        return _document_view(document)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json", exclude_unset=True),
        mutation,
    )


@router.put("/documents/{doc_key}/aliases")
async def update_document_aliases(
    doc_key: str,
    aliases: list[str],
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    normalized_aliases = _unique_values(aliases)

    async def mutation() -> dict[str, object]:
        document = await session.get(Document, doc_key)
        if document is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        before = {"aliases": document.aliases}
        document.aliases = normalized_aliases
        add_audit_record(
            session,
            actor=principal.name,
            action="document.aliases",
            target=doc_key,
            before=before,
            after={"aliases": normalized_aliases},
            trace_id=request.state.trace_id,
        )
        return _document_view(document)

    return await execute_idempotently(
        session,
        request,
        principal,
        {"aliases": normalized_aliases},
        mutation,
    )


@router.delete("/documents/{doc_key}")
async def archive_document(
    doc_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        document = await session.get(Document, doc_key)
        if document is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        draft = await ensure_draft(session, principal.name, "Archive document")
        before = {"status": document.status}
        document.status = "archived"
        keys = select(Chunk.id).where(Chunk.doc_key == doc_key)
        await session.execute(
            delete(ReleaseChunk)
            .where(ReleaseChunk.release_id == draft.id)
            .where(ReleaseChunk.chunk_id.in_(keys))
        )
        add_audit_record(
            session,
            actor=principal.name,
            action="document.archive",
            target=doc_key,
            before=before,
            after={"status": "archived"},
            trace_id=request.state.trace_id,
        )
        return {"status": "archived"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"doc_key": doc_key, "action": "archive"},
        mutation,
    )


@router.get("/chunks")
async def list_chunks(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    doc_key: str | None = None,
    before_key: str | None = None,
) -> dict[str, object]:
    release_id = await _current_release_id(session)
    if release_id is None:
        return {"items": [], "next_cursor": None}
    query = (
        select(Chunk)
        .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
        .where(ReleaseChunk.release_id == release_id)
        .order_by(Chunk.chunk_key.asc())
    )
    if doc_key is not None:
        query = query.where(Chunk.doc_key == doc_key)
    if before_key is not None:
        query = query.where(Chunk.chunk_key > before_key)
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [_chunk_view(row) for row in page],
        "next_cursor": page[-1].chunk_key if len(rows) > limit and page else None,
    }


@router.get("/chunks/{chunk_key}")
async def get_chunk(
    chunk_key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    chunk = await _current_chunk(session, chunk_key)
    if chunk is None:
        raise HTTPException(status_code=404, detail="chunk_not_found")
    return _chunk_view(chunk)


@router.get("/chunks/{chunk_key}/history")
async def get_chunk_history(
    chunk_key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    rows = (
        await session.scalars(
            select(Chunk).where(Chunk.chunk_key == chunk_key).order_by(Chunk.version.desc())
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="chunk_not_found")
    return {"items": [_chunk_view(row) for row in rows]}


@router.post("/chunks", status_code=status.HTTP_201_CREATED)
async def create_chunk(
    body: ChunkCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    settings = request.app.state.settings
    candidate = _build_candidate(
        body.chunk_key,
        body.doc_key,
        body.kind,
        body.text,
        body.embed_text,
        body.metadata,
        settings.chunk_hard_max_tokens,
    )
    vectors, model_id = await embed_documents(
        request,
        [candidate.embed_text or candidate.text],
    )
    vector = vectors[0]

    async def mutation() -> dict[str, object]:
        if await session.get(Document, candidate.doc_key) is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        draft = await ensure_draft(session, principal.name, "Create content chunk")
        if (await release_chunks(session, draft.id)).get(candidate.chunk_key) is not None:
            raise HTTPException(status_code=409, detail="chunk_already_exists")
        await _check_chunk_links(session, draft.id, candidate)
        chunk = await add_chunk_version(
            session,
            candidate,
            actor=principal.name,
            origin="manual",
            embedding=vector,
            embedding_model=model_id,
            change_note=body.change_note,
            trace_id=request.state.trace_id,
        )
        await attach_chunk(session, draft.id, chunk)
        add_audit_record(
            session,
            actor=principal.name,
            action="chunk.create",
            target=candidate.chunk_key,
            before=None,
            after={"doc_key": candidate.doc_key, "content_hash": candidate.content_hash},
            trace_id=request.state.trace_id,
        )
        return _chunk_view(chunk)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json"),
        mutation,
    )


@router.patch("/chunks/{chunk_key}")
async def update_chunk(
    chunk_key: str,
    body: ChunkPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    session_factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    async with session_factory() as read_session:
        current = await _current_chunk(read_session, chunk_key)
    if current is None:
        raise HTTPException(status_code=404, detail="chunk_not_found")
    text = body.text if body.text is not None else current.text
    embed_text = body.embed_text if body.embed_text is not None else current.embed_text
    metadata = body.metadata if body.metadata is not None else current.metadata_json
    settings = request.app.state.settings
    candidate = _build_candidate(
        chunk_key,
        current.doc_key,
        current.kind,
        text,
        embed_text,
        metadata,
        settings.chunk_hard_max_tokens,
    )
    vectors, model_id = await embed_documents(
        request,
        [candidate.embed_text or candidate.text],
    )
    vector = vectors[0]
    trace_id = body.trace_id or request.state.trace_id

    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Edit content chunk")
        latest = (await release_chunks(session, draft.id)).get(chunk_key)
        if latest is None:
            raise HTTPException(status_code=404, detail="chunk_not_found")
        await _check_chunk_links(session, draft.id, candidate)
        new_chunk = await add_chunk_version(
            session,
            candidate,
            actor=principal.name,
            origin="manual",
            embedding=vector,
            embedding_model=model_id,
            overrides_id=latest.id if latest.origin == "etl" else latest.overrides_id,
            change_note=body.change_note,
            trace_id=trace_id,
        )
        await attach_chunk(session, draft.id, new_chunk)
        add_audit_record(
            session,
            actor=principal.name,
            action="chunk.update",
            target=chunk_key,
            before={"content_hash": latest.content_hash, "version": latest.version},
            after={"content_hash": new_chunk.content_hash, "version": new_chunk.version},
            trace_id=request.state.trace_id,
        )
        return _chunk_view(new_chunk)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json", exclude_unset=True),
        mutation,
    )


@router.delete("/chunks/{chunk_key}")
async def suppress_chunk(
    chunk_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
    reason: str | None = Query(default=None, max_length=500),
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        draft = await ensure_draft(session, principal.name, "Suppress content chunk")
        current = (await release_chunks(session, draft.id)).get(chunk_key)
        if current is None:
            raise HTTPException(status_code=404, detail="chunk_not_found")
        await session.merge(
            Suppression(chunk_key=chunk_key, reason=reason, created_by=principal.name)
        )
        await remove_chunk_from_release(session, draft.id, chunk_key)
        add_audit_record(
            session,
            actor=principal.name,
            action="chunk.suppress",
            target=chunk_key,
            before={"version": current.version},
            after={"reason": reason},
            trace_id=request.state.trace_id,
        )
        return {"status": "suppressed"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"chunk_key": chunk_key, "reason": reason},
        mutation,
    )


@router.delete("/chunks/{chunk_key}/override")
async def remove_chunk_override(
    chunk_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        draft = await ensure_draft(session, principal.name, "Remove chunk override")
        current = (await release_chunks(session, draft.id)).get(chunk_key)
        if current is None or current.origin != "manual" or current.overrides_id is None:
            raise HTTPException(status_code=404, detail="chunk_override_not_found")
        await remove_chunk_from_release(session, draft.id, chunk_key)
        original = await session.get(Chunk, current.overrides_id)
        if original is not None:
            session.add(ReleaseChunk(release_id=draft.id, chunk_id=original.id))
        add_audit_record(
            session,
            actor=principal.name,
            action="chunk.override.remove",
            target=chunk_key,
            before={"version": current.version},
            after={"restored_version": original.version if original else None},
            trace_id=request.state.trace_id,
        )
        return {"status": "override_removed"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"chunk_key": chunk_key, "action": "remove_override"},
        mutation,
    )


@router.get("/suppressions")
async def list_suppressions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_key: str | None = None,
) -> dict[str, object]:
    query = select(Suppression).order_by(Suppression.chunk_key.asc())
    if before_key is not None:
        query = query.where(Suppression.chunk_key > before_key)
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [
            {
                "chunk_key": row.chunk_key,
                "reason": row.reason,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
            for row in page
        ],
        "next_cursor": page[-1].chunk_key if len(rows) > limit and page else None,
    }


@router.delete("/suppressions/{chunk_key}")
async def delete_suppression(
    chunk_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        suppression = await session.get(Suppression, chunk_key)
        if suppression is None:
            raise HTTPException(status_code=404, detail="suppression_not_found")
        await session.delete(suppression)
        add_audit_record(
            session,
            actor=principal.name,
            action="suppression.remove",
            target=chunk_key,
            before={"reason": suppression.reason},
            after=None,
            trace_id=request.state.trace_id,
        )
        return {"status": "removed"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"chunk_key": chunk_key, "action": "remove_suppression"},
        mutation,
    )


def _apply_document_patch(document: Document, body: DocumentPatch) -> None:
    if body.title is not None:
        document.title = body.title.strip()
    if "url_path" in body.model_fields_set:
        document.url_path = body.url_path
    if body.aliases is not None:
        document.aliases = _unique_values(body.aliases)
    document.updated_at = datetime.now(UTC)


def _unique_values(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    if len(normalized) > 50 or any(len(value) > 100 for value in normalized):
        raise HTTPException(status_code=422, detail="invalid_aliases")
    if len(normalized) != len(set(normalized)):
        raise HTTPException(status_code=422, detail="values_must_be_unique")
    return normalized


def _document_view(document: Document) -> dict[str, object]:
    return {
        "doc_key": document.doc_key,
        "doc_type": document.doc_type,
        "title": document.title,
        "url_path": document.url_path,
        "origin": document.origin,
        "source_id": document.source_id,
        "aliases": document.aliases,
        "status": document.status,
        "updated_at": document.updated_at,
    }


def _chunk_view(chunk: Chunk) -> dict[str, object]:
    return {
        "id": chunk.id,
        "chunk_key": chunk.chunk_key,
        "doc_key": chunk.doc_key,
        "version": chunk.version,
        "kind": chunk.kind,
        "origin": chunk.origin,
        "overrides_id": chunk.overrides_id,
        "text": chunk.text,
        "embed_text": chunk.embed_text,
        "token_count": chunk.token_count,
        "metadata": chunk.metadata_json,
        "content_hash": chunk.content_hash,
        "embedding_model": chunk.embedding_model,
        "created_by": chunk.created_by,
        "created_via": chunk.created_via,
        "change_note": chunk.change_note,
        "trace_id": chunk.trace_id,
        "created_at": chunk.created_at,
    }


def _build_candidate(
    chunk_key: str,
    doc_key: str,
    kind: str,
    text: str,
    embed_text: str | None,
    metadata: dict[str, Any],
    max_tokens: int,
) -> ContentChunk:
    try:
        return build_manual_chunk(
            chunk_key,
            doc_key,
            kind,
            text,
            embed_text,
            metadata,
            max_tokens,
        )
    except ContentValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc


async def _check_chunk_links(
    session: AsyncSession,
    release_id: int,
    chunk: ContentChunk,
) -> None:
    value = chunk.metadata.get("link_keys", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=422, detail="invalid_chunk_link_keys")
    try:
        await validate_link_keys(session, release_id, value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unknown_chunk_link_key") from exc


async def _current_release_id(session: AsyncSession) -> int | None:
    draft_id = await session.scalar(select(Release.id).where(Release.status == "draft"))
    return draft_id if draft_id is not None else await active_release_id(session)


async def _current_chunk(session: AsyncSession, chunk_key: str) -> Chunk | None:
    release_id = await _current_release_id(session)
    if release_id is None:
        return None
    result = await session.scalars(
        select(Chunk)
        .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
        .where(ReleaseChunk.release_id == release_id, Chunk.chunk_key == chunk_key)
    )
    return result.first()
