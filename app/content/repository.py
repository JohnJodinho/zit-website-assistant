from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import ContentChunk, SourceDocument, SourceLink
from app.db.models import (
    AuditLog,
    Chunk,
    Document,
    Link,
    Release,
    ReleaseChunk,
    ReleaseLink,
    Setting,
    Source,
)


async def active_release_id(session: AsyncSession) -> int | None:
    setting = await session.get(Setting, "active_release_id")
    if setting is None:
        return None
    value = setting.value.get("value", setting.value.get("release_id"))
    return value if type(value) is int else None


async def ensure_draft(session: AsyncSession, actor: str, note: str | None = None) -> Release:
    draft = await session.scalar(select(Release).where(Release.status == "draft").with_for_update())
    if draft is not None:
        return draft

    parent_id = await active_release_id(session)
    draft = Release(status="draft", parent_id=parent_id, note=note, created_by=actor)
    session.add(draft)
    await session.flush()
    if parent_id is not None:
        chunk_ids = select(ReleaseChunk.chunk_id).where(ReleaseChunk.release_id == parent_id)
        link_ids = select(ReleaseLink.link_id).where(ReleaseLink.release_id == parent_id)
        for chunk_id in (await session.scalars(chunk_ids)).all():
            session.add(ReleaseChunk(release_id=draft.id, chunk_id=chunk_id))
        for link_id in (await session.scalars(link_ids)).all():
            session.add(ReleaseLink(release_id=draft.id, link_id=link_id))
        await session.flush()
    return draft


async def release_chunks(session: AsyncSession, release_id: int) -> dict[str, Chunk]:
    rows = (
        await session.scalars(
            select(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
    ).all()
    return {row.chunk_key: row for row in rows}


async def release_links(session: AsyncSession, release_id: int) -> dict[str, Link]:
    rows = (
        await session.scalars(
            select(Link)
            .join(ReleaseLink, ReleaseLink.link_id == Link.id)
            .where(ReleaseLink.release_id == release_id)
        )
    ).all()
    return {row.link_key: row for row in rows}


async def save_source(
    session: AsyncSession,
    *,
    kind: str,
    name: str,
    payload_hash: str,
) -> Source:
    source = await session.scalar(select(Source).where(Source.kind == kind, Source.name == name))
    if source is None:
        source = Source(kind=kind, name=name)
        session.add(source)
    source.last_payload_hash = payload_hash
    return source


async def save_document(
    session: AsyncSession,
    source_document: SourceDocument,
    source_id: UUID,
    *,
    origin: str,
) -> Document:
    document = await session.get(Document, source_document.doc_key)
    if document is None:
        document = Document(
            doc_key=source_document.doc_key,
            doc_type=source_document.doc_type,
            title=source_document.title,
            url_path=source_document.url_path,
            origin=origin,
            source_id=source_id,
            aliases=[],
            status="active",
        )
        session.add(document)
        return document
    if document.origin == "manual" and origin == "etl":
        return document
    document.doc_type = source_document.doc_type
    document.title = source_document.title
    document.url_path = source_document.url_path
    document.source_id = source_id
    document.status = "active"
    return document


async def add_chunk_version(
    session: AsyncSession,
    candidate: ContentChunk,
    *,
    actor: str,
    origin: str,
    embedding: list[float] | None,
    embedding_model: str | None,
    overrides_id: UUID | None = None,
    change_note: str | None = None,
    trace_id: UUID | None = None,
) -> Chunk:
    current_version = await session.scalar(
        select(func.max(Chunk.version)).where(Chunk.chunk_key == candidate.chunk_key)
    )
    chunk = Chunk(
        id=uuid4(),
        chunk_key=candidate.chunk_key,
        doc_key=candidate.doc_key,
        version=(current_version or 0) + 1,
        kind=candidate.kind,
        origin=origin,
        overrides_id=overrides_id,
        text=candidate.text,
        embed_text=candidate.embed_text,
        token_count=candidate.token_count,
        metadata_json=candidate.metadata,
        content_hash=candidate.content_hash,
        embedding=embedding,
        embedding_model=embedding_model,
        created_by=actor,
        created_via="etl" if origin == "etl" else "admin_api",
        change_note=change_note,
        trace_id=trace_id,
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def attach_chunk(session: AsyncSession, release_id: int, chunk: Chunk) -> None:
    await session.execute(
        delete(ReleaseChunk)
        .where(ReleaseChunk.release_id == release_id)
        .where(
            ReleaseChunk.chunk_id.in_(select(Chunk.id).where(Chunk.chunk_key == chunk.chunk_key))
        )
    )
    session.add(ReleaseChunk(release_id=release_id, chunk_id=chunk.id))


async def add_link_version(
    session: AsyncSession,
    candidate: SourceLink,
    *,
    actor: str,
    origin: str,
    release_id: int,
    description: str = "",
    aliases: Sequence[str] = (),
    doc_key: str | None = None,
    priority: int = 50,
    active: bool = True,
) -> Link:
    current_version = await session.scalar(
        select(func.max(Link.version)).where(Link.link_key == candidate.link_key)
    )
    link = Link(
        id=uuid4(),
        link_key=candidate.link_key,
        version=(current_version or 0) + 1,
        kind=candidate.kind,
        label=candidate.label,
        url=candidate.url,
        description=description,
        aliases=list(aliases),
        doc_key=doc_key,
        priority=priority,
        active=active,
        origin=origin,
        created_by=actor,
    )
    session.add(link)
    await session.flush()
    await attach_link(session, release_id, link)
    return link


async def attach_link(session: AsyncSession, release_id: int, link: Link) -> None:
    await session.execute(
        delete(ReleaseLink)
        .where(ReleaseLink.release_id == release_id)
        .where(ReleaseLink.link_id.in_(select(Link.id).where(Link.link_key == link.link_key)))
    )
    session.add(ReleaseLink(release_id=release_id, link_id=link.id))


async def remove_chunk_from_release(
    session: AsyncSession,
    release_id: int,
    chunk_key: str,
) -> None:
    await session.execute(
        delete(ReleaseChunk)
        .where(ReleaseChunk.release_id == release_id)
        .where(ReleaseChunk.chunk_id.in_(select(Chunk.id).where(Chunk.chunk_key == chunk_key)))
    )


async def remove_link_from_release(
    session: AsyncSession,
    release_id: int,
    link_key: str,
) -> None:
    await session.execute(
        delete(ReleaseLink)
        .where(ReleaseLink.release_id == release_id)
        .where(ReleaseLink.link_id.in_(select(Link.id).where(Link.link_key == link_key)))
    )


async def validate_link_keys(
    session: AsyncSession,
    release_id: int,
    link_keys: Sequence[str],
) -> None:
    if not link_keys:
        return
    known_keys = set(
        (
            await session.scalars(
                select(Link.link_key)
                .join(ReleaseLink, ReleaseLink.link_id == Link.id)
                .where(
                    ReleaseLink.release_id == release_id,
                    Link.active.is_(True),
                    Link.link_key.in_(link_keys),
                )
            )
        ).all()
    )
    missing = set(link_keys) - known_keys
    if missing:
        raise ValueError(f"Unknown link keys: {', '.join(sorted(missing))}")


def add_audit_record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    target: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    trace_id: UUID | None,
) -> None:
    session.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            before=before,
            after=after,
            trace_id=trace_id,
        )
    )
