from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.content.diff import (
    ContentDiff,
    DiffSafety,
    ExistingChunk,
    check_diff_safety,
    diff_chunks,
)
from app.content.models import CrawlImport
from app.content.repository import (
    active_release_id,
    add_audit_record,
    ensure_draft,
    release_chunks,
    release_links,
    save_source,
)
from app.db.models import (
    Chunk,
    Document,
    IngestionEvent,
    IngestionRun,
    Link,
    Release,
    ReleaseChunk,
    ReleaseLink,
    Source,
    Suppression,
)
from app.embeddings.client import BGE_MODEL_ID, BgeEmbeddingClient


class IngestionConflict(RuntimeError):
    pass


async def stage_crawl(
    session_factory: async_sessionmaker[AsyncSession],
    crawl: CrawlImport,
    embeddings: BgeEmbeddingClient,
    settings: Settings,
    *,
    actor: str,
    trace_id: UUID,
    force: bool = False,
) -> dict[str, object]:
    run = await _start_run(session_factory, crawl, actor, trace_id)
    try:
        result = await _stage_run(
            session_factory,
            run,
            crawl,
            embeddings,
            settings,
            actor=actor,
            trace_id=trace_id,
            force=force,
        )
    except Exception as exc:
        await _fail_run(session_factory, run.id, type(exc).__name__)
        raise
    return result


async def _start_run(
    session_factory: async_sessionmaker[AsyncSession],
    crawl: CrawlImport,
    actor: str,
    trace_id: UUID,
) -> IngestionRun:
    run = IngestionRun(
        source_kind="crawl_md",
        mode="stage",
        status="running",
        payload_hash=crawl.payload_hash,
        requested_by=actor,
        trace_id=trace_id,
    )
    async with session_factory() as session:
        session.add(run)
        try:
            await session.flush()
            session.add(
                IngestionEvent(
                    run_id=run.id,
                    stage="start",
                    action="started",
                    detail={"payload_hash": crawl.payload_hash},
                )
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise IngestionConflict("another_ingestion_is_running") from exc
    return run


async def _stage_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: IngestionRun,
    crawl: CrawlImport,
    embeddings: BgeEmbeddingClient,
    settings: Settings,
    *,
    actor: str,
    trace_id: UUID,
    force: bool,
) -> dict[str, object]:
    async with session_factory() as session:
        source = await session.scalar(
            select(Source).where(Source.kind == "crawl_md", Source.name == "approved-crawl")
        )
        if source is not None and source.last_payload_hash == crawl.payload_hash and not force:
            return await _finish_noop(session, run, trace_id)

        base_release_id = await _base_release_id(session)
        existing_rows = (
            (
                await session.execute(
                    select(Chunk, ReleaseChunk)
                    .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
                    .where(ReleaseChunk.release_id == base_release_id)
                )
            ).all()
            if base_release_id is not None
            else []
        )
        existing = {
            chunk.chunk_key: ExistingChunk(chunk.content_hash, chunk.origin)
            for chunk, _ in existing_rows
        }
        suppressions = set((await session.scalars(select(Suppression.chunk_key))).all())
        diff = diff_chunks(existing, crawl.chunks, suppressions)
        safety = check_diff_safety(
            len(existing),
            len(crawl.chunks),
            len(diff.removed),
            max_removal_percent=settings.etl_max_removal_percent,
            max_count_swing_percent=settings.etl_max_count_swing_percent,
            force=force,
        )
        _validate_import(crawl, settings, safety)

    to_embed = (*diff.added, *diff.changed)
    vectors = (
        await embeddings.embed_texts(
            [chunk.text for chunk in to_embed],
            input_type="document",
        )
        if to_embed
        else []
    )
    vector_map = {chunk.chunk_key: vector for chunk, vector in zip(to_embed, vectors, strict=True)}
    return await _commit_stage(
        session_factory,
        run,
        crawl,
        diff,
        vector_map,
        settings,
        actor=actor,
        trace_id=trace_id,
        force=force,
        expected_release_id=base_release_id,
        expected_existing=existing,
    )


async def _commit_stage(
    session_factory: async_sessionmaker[AsyncSession],
    run: IngestionRun,
    crawl: CrawlImport,
    diff: ContentDiff,
    vectors: Mapping[str, list[float]],
    settings: Settings,
    *,
    actor: str,
    trace_id: UUID,
    force: bool,
    expected_release_id: int | None,
    expected_existing: Mapping[str, ExistingChunk],
) -> dict[str, object]:
    from app.content.diff import ContentDiff

    if not isinstance(diff, ContentDiff):
        raise TypeError("Invalid content diff")

    async with session_factory() as session, session.begin():
        current_base_id = await _base_release_id(session, lock=True)
        current_rows = (
            (
                await session.execute(
                    select(Chunk, ReleaseChunk)
                    .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
                    .where(ReleaseChunk.release_id == current_base_id)
                )
            ).all()
            if current_base_id is not None
            else []
        )
        current = {
            chunk.chunk_key: ExistingChunk(chunk.content_hash, chunk.origin)
            for chunk, _ in current_rows
        }
        if current_base_id != expected_release_id or current != expected_existing:
            raise IngestionConflict("content_changed_while_embeddings_were_created")
        if not force and await _source_hash_matches(session, crawl.payload_hash):
            raise IngestionConflict("crawl_was_staged_concurrently")

        draft = await ensure_draft(session, actor, "ETL crawl import")
        source = await save_source(
            session,
            kind="crawl_md",
            name="approved-crawl",
            payload_hash=crawl.payload_hash,
        )
        await session.flush()
        run_record = await session.get(IngestionRun, run.id)
        if run_record is None:
            raise RuntimeError("Ingestion run record disappeared")
        await _save_crawl_documents(session, crawl, source.id)
        await _stage_crawl_links(session, draft.id, crawl, actor)
        await _stage_crawl_chunks(
            session,
            draft.id,
            diff,
            vectors,
            actor=actor,
            trace_id=trace_id,
        )

        stats = _stats(crawl, diff, force)
        run_record.status = "succeeded"
        run_record.release_id = draft.id
        run_record.finished_at = datetime.now(UTC)
        run_record.stats = stats
        run_record.warnings = {
            "items": list(crawl.warnings),
            "source_conflicts": list(crawl.source_conflicts),
            "safety": [],
        }
        session.add(
            IngestionEvent(
                run_id=run.id,
                stage="stage",
                action="completed",
                detail=stats,
            )
        )
        if force:
            add_audit_record(
                session,
                actor=actor,
                action="etl.force_stage",
                target=str(run.id),
                before=None,
                after=stats,
                trace_id=trace_id,
            )
        add_audit_record(
            session,
            actor=actor,
            action="etl.stage",
            target=str(run.id),
            before=None,
            after=stats,
            trace_id=trace_id,
        )
        return {
            "run_id": str(run.id),
            "status": run_record.status,
            "release_id": draft.id,
            **stats,
        }


async def _save_crawl_documents(
    session: AsyncSession,
    crawl: CrawlImport,
    source_id: UUID,
) -> None:
    doc_keys = [document.doc_key for document in crawl.documents]
    existing = (await session.scalars(select(Document).where(Document.doc_key.in_(doc_keys)))).all()
    existing_by_key = {document.doc_key: document for document in existing}
    for source_document in crawl.documents:
        document = existing_by_key.get(source_document.doc_key)
        if document is None:
            session.add(
                Document(
                    doc_key=source_document.doc_key,
                    doc_type=source_document.doc_type,
                    title=source_document.title,
                    url_path=source_document.url_path,
                    origin="etl",
                    source_id=source_id,
                    aliases=[],
                    status="active",
                )
            )
        elif document.origin != "manual":
            document.doc_type = source_document.doc_type
            document.title = source_document.title
            document.url_path = source_document.url_path
            document.source_id = source_id
            document.status = "active"


async def _stage_crawl_links(
    session: AsyncSession,
    release_id: int,
    crawl: CrawlImport,
    actor: str,
) -> None:
    links_before = await release_links(session, release_id)
    incoming = {item.link_key: item for item in crawl.links}
    links_to_add = [
        candidate
        for key, candidate in incoming.items()
        if (previous := links_before.get(key)) is None
        or (previous.url, previous.label) != (candidate.url, candidate.label)
    ]
    removed_keys = {
        key
        for key, previous in links_before.items()
        if previous.origin == "etl" and key not in incoming
    }
    replaced_keys = {link.link_key for link in links_to_add} | removed_keys
    if replaced_keys:
        await session.execute(
            delete(ReleaseLink)
            .where(ReleaseLink.release_id == release_id)
            .where(ReleaseLink.link_id.in_(select(Link.id).where(Link.link_key.in_(replaced_keys))))
        )
    if not links_to_add:
        return

    link_versions = await session.execute(
        select(Link.link_key, func.max(Link.version))
        .where(Link.link_key.in_([link.link_key for link in links_to_add]))
        .group_by(Link.link_key)
    )
    max_versions: dict[str, int] = dict(link_versions.tuples().all())
    links = [
        Link(
            id=uuid4(),
            link_key=candidate.link_key,
            version=(max_versions.get(candidate.link_key) or 0) + 1,
            kind=candidate.kind,
            label=candidate.label,
            url=candidate.url,
            description="",
            aliases=[],
            doc_key=None,
            priority=50,
            active=True,
            origin="etl",
            created_by=actor,
        )
        for candidate in links_to_add
    ]
    session.add_all(links)
    await session.flush()
    session.add_all(ReleaseLink(release_id=release_id, link_id=link.id) for link in links)


async def _stage_crawl_chunks(
    session: AsyncSession,
    release_id: int,
    diff: ContentDiff,
    vectors: Mapping[str, list[float]],
    *,
    actor: str,
    trace_id: UUID,
) -> None:
    candidates = (*diff.added, *diff.changed)
    replacement_keys = {key for key in diff.removed}
    replacement_keys.update(candidate.chunk_key for candidate in candidates)
    if replacement_keys:
        await session.execute(
            delete(ReleaseChunk)
            .where(ReleaseChunk.release_id == release_id)
            .where(
                ReleaseChunk.chunk_id.in_(
                    select(Chunk.id).where(Chunk.chunk_key.in_(replacement_keys))
                )
            )
        )
    if not candidates:
        return

    draft_chunks = await release_chunks(session, release_id)
    chunk_versions = await session.execute(
        select(Chunk.chunk_key, func.max(Chunk.version))
        .where(Chunk.chunk_key.in_([chunk.chunk_key for chunk in candidates]))
        .group_by(Chunk.chunk_key)
    )
    max_versions: dict[str, int] = dict(chunk_versions.tuples().all())
    chunks = [
        Chunk(
            id=uuid4(),
            chunk_key=candidate.chunk_key,
            doc_key=candidate.doc_key,
            version=(max_versions.get(candidate.chunk_key) or 0) + 1,
            kind=candidate.kind,
            origin="etl",
            overrides_id=(
                draft_chunks[candidate.chunk_key].id
                if candidate.chunk_key in draft_chunks
                else None
            ),
            text=candidate.text,
            embed_text=candidate.embed_text,
            token_count=candidate.token_count,
            metadata_json=candidate.metadata,
            content_hash=candidate.content_hash,
            embedding=vectors[candidate.chunk_key],
            embedding_model=BGE_MODEL_ID,
            created_by=actor,
            created_via="etl",
            change_note=None,
            trace_id=trace_id,
        )
        for candidate in candidates
    ]
    session.add_all(chunks)
    await session.flush()
    session.add_all(ReleaseChunk(release_id=release_id, chunk_id=chunk.id) for chunk in chunks)


def _validate_import(crawl: CrawlImport, settings: Settings, safety: DiffSafety) -> None:
    if not crawl.supporting_sources_loaded:
        raise ValueError("Both approved supporting JSON sources are required for staging")
    if not crawl.chunks or not crawl.documents:
        raise ValueError("The crawl produced no importable content")
    if any(chunk.token_count > settings.chunk_hard_max_tokens for chunk in crawl.chunks):
        raise ValueError("The crawl contains chunks above CHUNK_HARD_MAX_TOKENS")
    total_courses = max(crawl.report.course_pages, 1)
    missing_courses = sum(
        1
        for chunk in crawl.chunks
        if chunk.kind == "course_facts"
        and any(
            not chunk.metadata.get(field)
            for field in (
                "category",
                "programme",
                "duration",
                "tuition",
                "overview",
                "outcomes",
                "skills",
                "careers",
                "entry_requirements",
                "certification",
            )
        )
    )
    if missing_courses / total_courses * 100 > settings.etl_missing_section_fail_percent:
        raise ValueError("The crawl exceeds the missing-required-course-field threshold")
    if not safety.allowed:
        violations = ", ".join(safety.violations)
        raise ValueError(f"ETL safety check failed: {violations}")


async def _base_release_id(session: AsyncSession, *, lock: bool = False) -> int | None:
    draft_query = select(Release.id).where(Release.status == "draft")
    if lock:
        draft_query = draft_query.with_for_update()
    draft_id = await session.scalar(draft_query)
    return draft_id if draft_id is not None else await active_release_id(session)


async def _source_hash_matches(session: AsyncSession, payload_hash: str) -> bool:
    source = await session.scalar(
        select(Source).where(Source.kind == "crawl_md", Source.name == "approved-crawl")
    )
    return source is not None and source.last_payload_hash == payload_hash


async def _finish_noop(
    session: AsyncSession,
    run: IngestionRun,
    trace_id: UUID,
) -> dict[str, object]:
    run_record = await session.get(IngestionRun, run.id)
    if run_record is None:
        raise RuntimeError("Ingestion run record disappeared")
    run_record.status = "succeeded"
    run_record.finished_at = datetime.now(UTC)
    run_record.stats = {"no_op": True, "reason": "payload_unchanged"}
    session.add(
        IngestionEvent(
            run_id=run.id,
            stage="compare",
            action="unchanged",
            detail=run_record.stats,
        )
    )
    add_audit_record(
        session,
        actor=run.requested_by,
        action="etl.noop",
        target=str(run.id),
        before=None,
        after=run_record.stats,
        trace_id=trace_id,
    )
    await session.commit()
    return {"run_id": str(run.id), "status": "succeeded", **run_record.stats}


async def _fail_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    error_code: str,
) -> None:
    async with session_factory() as session, session.begin():
        run = await session.get(IngestionRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = error_code
        session.add(
            IngestionEvent(
                run_id=run.id,
                stage="stage",
                action="error",
                detail={"error_code": error_code},
            )
        )


def _stats(crawl: CrawlImport, diff: ContentDiff, force: bool) -> dict[str, object]:
    return {
        "payload_hash": crawl.payload_hash,
        "documents": len(crawl.documents),
        "chunks": len(crawl.chunks),
        "links": len(crawl.links),
        "added": len(diff.added),
        "changed": len(diff.changed),
        "removed": len(diff.removed),
        "unchanged": len(diff.unchanged),
        "conflicts": list(diff.conflicts),
        "source_conflicts": list(crawl.source_conflicts),
        "suppressed": list(diff.suppressed),
        "forced": force,
    }
