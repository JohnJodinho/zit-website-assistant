from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
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
    add_chunk_version,
    add_link_version,
    attach_chunk,
    ensure_draft,
    release_chunks,
    release_links,
    remove_chunk_from_release,
    remove_link_from_release,
    save_document,
    save_source,
)
from app.db.models import (
    Chunk,
    IngestionEvent,
    IngestionRun,
    Release,
    ReleaseChunk,
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
        for document in crawl.documents:
            await save_document(session, document, source.id, origin="etl")

        links_before = await release_links(session, draft.id)
        for candidate_link in crawl.links:
            previous = links_before.get(candidate_link.link_key)
            if previous is not None and (
                previous.url,
                previous.label,
            ) == (candidate_link.url, candidate_link.label):
                continue
            await add_link_version(
                session,
                candidate_link,
                actor=actor,
                origin="etl",
                release_id=draft.id,
            )
        incoming_link_keys = {item.link_key for item in crawl.links}
        for key, previous_link in links_before.items():
            if previous_link.origin == "etl" and key not in incoming_link_keys:
                await remove_link_from_release(session, draft.id, key)

        for key in diff.removed:
            await remove_chunk_from_release(session, draft.id, key)
        draft_chunks = await release_chunks(session, draft.id)
        for candidate in (*diff.added, *diff.changed):
            current_chunk = draft_chunks.get(candidate.chunk_key)
            chunk = await add_chunk_version(
                session,
                candidate,
                actor=actor,
                origin="etl",
                embedding=vectors[candidate.chunk_key],
                embedding_model=BGE_MODEL_ID,
                overrides_id=current_chunk.id if current_chunk else None,
                trace_id=trace_id,
            )
            await attach_chunk(session, draft.id, chunk)
            draft_chunks[candidate.chunk_key] = chunk

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
