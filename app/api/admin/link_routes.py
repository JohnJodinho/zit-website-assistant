from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_scope
from app.content.idempotency import execute_idempotently
from app.content.models import SourceLink
from app.content.repository import (
    active_release_id,
    add_audit_record,
    add_link_version,
    ensure_draft,
    release_links,
    remove_link_from_release,
)
from app.content.schemas import LinkCreate, LinkPatch
from app.db.models import Chunk, Document, Link, Release, ReleaseChunk, ReleaseLink
from app.db.session import get_db_session
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["content links"])
_SITE_HOSTS = {"www.zibeh.ng", "zibeh.ng"}


@router.get("/links")
async def list_links(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    limit: int = Query(default=50, ge=1, le=100),
    before_key: str | None = None,
    active: bool | None = None,
) -> dict[str, object]:
    release_id = await _current_release_id(session)
    if release_id is None:
        return {"items": [], "next_cursor": None}
    query = (
        select(Link)
        .join(ReleaseLink, ReleaseLink.link_id == Link.id)
        .where(ReleaseLink.release_id == release_id)
        .order_by(Link.link_key.asc())
    )
    if before_key is not None:
        query = query.where(Link.link_key > before_key)
    if active is not None:
        query = query.where(Link.active.is_(active))
    rows = (await session.scalars(query.limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [_link_view(row) for row in page],
        "next_cursor": page[-1].link_key if len(rows) > limit and page else None,
    }


@router.get("/links/{link_key}")
async def get_link(
    link_key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    release_id = await _current_release_id(session)
    link = (await _links_for_release(session, release_id)).get(link_key) if release_id else None
    if link is None:
        raise HTTPException(status_code=404, detail="link_not_found")
    return _link_view(link)


@router.post("/links", status_code=status.HTTP_201_CREATED)
async def create_link(
    body: LinkCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    url = str(body.url)
    _validate_site_url(url)
    _validate_description(body.description)

    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Create link")
        if body.link_key in await release_links(session, draft.id):
            raise HTTPException(status_code=409, detail="link_already_exists")
        await _validate_document(session, body.doc_key)
        link = await add_link_version(
            session,
            _source_link(body.link_key, body.kind, body.label, url),
            actor=principal.name,
            origin="manual",
            release_id=draft.id,
            description=body.description,
            aliases=body.aliases,
            doc_key=body.doc_key,
            priority=body.priority,
            active=body.active,
        )
        add_audit_record(
            session,
            actor=principal.name,
            action="link.create",
            target=body.link_key,
            before=None,
            after=_link_view(link),
            trace_id=request.state.trace_id,
        )
        return _link_view(link)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json"),
        mutation,
    )


@router.patch("/links/{link_key}")
async def update_link(
    link_key: str,
    body: LinkPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Update link")
        current = (await release_links(session, draft.id)).get(link_key)
        if current is None:
            raise HTTPException(status_code=404, detail="link_not_found")
        url = str(body.url) if body.url is not None else current.url
        _validate_site_url(url)
        description = body.description if body.description is not None else current.description
        _validate_description(description)
        doc_key = body.doc_key if "doc_key" in body.model_fields_set else current.doc_key
        await _validate_document(session, doc_key)
        updated = await add_link_version(
            session,
            _source_link(
                link_key,
                current.kind,
                body.label if body.label is not None else current.label,
                url,
            ),
            actor=principal.name,
            origin="manual",
            release_id=draft.id,
            description=description,
            aliases=body.aliases if body.aliases is not None else current.aliases,
            doc_key=doc_key,
            priority=body.priority if body.priority is not None else current.priority,
            active=body.active if body.active is not None else current.active,
        )
        add_audit_record(
            session,
            actor=principal.name,
            action="link.update",
            target=link_key,
            before=_link_view(current),
            after=_link_view(updated),
            trace_id=request.state.trace_id,
        )
        return _link_view(updated)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json", exclude_unset=True),
        mutation,
    )


@router.delete("/links/{link_key}")
async def delete_link(
    link_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    async def mutation() -> dict[str, str]:
        draft = await ensure_draft(session, principal.name, "Remove link")
        current = (await release_links(session, draft.id)).get(link_key)
        if current is None:
            raise HTTPException(status_code=404, detail="link_not_found")
        await remove_link_from_release(session, draft.id, link_key)
        add_audit_record(
            session,
            actor=principal.name,
            action="link.remove",
            target=link_key,
            before=_link_view(current),
            after=None,
            trace_id=request.state.trace_id,
        )
        return {"status": "removed"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"link_key": link_key, "action": "remove"},
        mutation,
    )


@router.post("/links/validate")
async def validate_links(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    release_id = await _current_release_id(session)
    if release_id is None:
        return {"valid": False, "errors": ["no_release_available"]}
    links = await _links_for_release(session, release_id)
    chunks = await _chunks_for_release(session, release_id)
    errors = [
        {"code": "invalid_link_url", "link_key": key}
        for key, link in links.items()
        if not _is_allowed_url(link.url)
    ]
    link_keys = {key for key, link in links.items() if link.active}
    for chunk in chunks:
        referenced = chunk.metadata_json.get("link_keys", [])
        if not isinstance(referenced, list):
            errors.append({"code": "invalid_chunk_link_keys", "chunk_key": chunk.chunk_key})
            continue
        errors.extend(
            {"code": "unknown_chunk_link_key", "chunk_key": chunk.chunk_key, "link_key": key}
            for key in referenced
            if isinstance(key, str) and key not in link_keys
        )
    errors.extend(_course_link_errors(chunks, link_keys))
    if "contact:admissions" not in link_keys:
        errors.append({"code": "contact_link_missing"})
    return {"valid": not errors, "errors": errors}


def _validate_site_url(value: str) -> None:
    if not _is_allowed_url(value):
        raise HTTPException(status_code=422, detail="link_url_not_allowed")


def _is_allowed_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _SITE_HOSTS
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


async def _validate_document(session: AsyncSession, doc_key: str | None) -> None:
    if doc_key is not None and await session.get(Document, doc_key) is None:
        raise HTTPException(status_code=404, detail="document_not_found")


async def _current_release_id(session: AsyncSession) -> int | None:
    draft_id = await session.scalar(select(Release.id).where(Release.status == "draft"))
    return draft_id if draft_id is not None else await active_release_id(session)


async def _links_for_release(session: AsyncSession, release_id: int) -> dict[str, Link]:
    rows = (
        await session.scalars(
            select(Link)
            .join(ReleaseLink, ReleaseLink.link_id == Link.id)
            .where(ReleaseLink.release_id == release_id)
        )
    ).all()
    return {link.link_key: link for link in rows}


async def _chunks_for_release(
    session: AsyncSession,
    release_id: int,
) -> Sequence[Chunk]:
    return (
        await session.scalars(
            select(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
    ).all()


def _course_link_errors(
    chunks: Sequence[Chunk],
    link_keys: set[str],
) -> list[dict[str, str]]:
    course_keys = {chunk.doc_key for chunk in chunks if chunk.doc_key.startswith("course:")}
    errors: list[dict[str, str]] = []
    for doc_key in course_keys:
        slug = doc_key.removeprefix("course:")
        for required_key in (f"course:{slug}", f"apply:{slug}"):
            if required_key not in link_keys:
                errors.append({"code": "required_course_link_missing", "doc_key": doc_key})
    return errors


def _source_link(link_key: str, kind: str, label: str, url: str) -> SourceLink:
    return SourceLink(link_key=link_key, kind=kind, label=label, url=url)


def _validate_description(description: str) -> None:
    if len(description.split()) > 15:
        raise HTTPException(status_code=422, detail="link_description_too_long")


def _link_view(link: Link) -> dict[str, object]:
    return {
        "id": link.id,
        "link_key": link.link_key,
        "version": link.version,
        "kind": link.kind,
        "label": link.label,
        "url": link.url,
        "description": link.description,
        "aliases": link.aliases,
        "doc_key": link.doc_key,
        "priority": link.priority,
        "active": link.active,
        "origin": link.origin,
        "created_by": link.created_by,
        "created_at": link.created_at,
    }
