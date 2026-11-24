from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.api.admin.release_routes import _release_content_hash, _release_records
from app.config import Settings, get_settings
from app.content.repository import active_release_id
from app.db.models import (
    ApiKey,
    AuditLog,
    Chunk,
    IdempotencyRecord,
    Release,
    ReleaseChunk,
    ReleaseLink,
    Setting,
    Trace,
)
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.security.keys import AdminScope, generate_admin_key
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_RELEASE_PREFIX = "zzdrill-publish-rollback-"
_KEY_PREFIX = "zzdrill-agent-drill-temp-"
_TRACE_FLAG = "zzdrill-publish-rollback"


class DrillFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DrillResources:
    run_tag: str
    active_release_id: int
    active_chunk_count: int
    active_updated_by: str | None
    release_id: int
    key_id: UUID
    key_name: str
    raw_key: str = field(repr=False)

    @property
    def publish_key(self) -> str:
        return f"zzdrill-publish-{self.run_tag}"

    @property
    def rollback_key(self) -> str:
        return f"zzdrill-rollback-{self.run_tag}"


async def _baseline(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, str | None]:
    async with factory() as session:
        active_setting = await session.get(Setting, "active_release_id")
        release_id = await active_release_id(session)
        if release_id is None or active_setting is None:
            raise DrillFailure("active_release_missing")
        release = await session.get(Release, release_id)
        if release is None or release.status != "published":
            raise DrillFailure("active_release_not_published")
        drafts = await session.scalar(
            select(func.count()).select_from(Release).where(Release.status == "draft")
        )
        if drafts:
            raise DrillFailure("open_draft_exists")
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
        drill_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(
                ReleaseChunk.release_id == release_id,
                Chunk.doc_key.startswith("zzdrill-"),
            )
        )
        if drill_count:
            raise DrillFailure("active_release_has_drill_content")
        return release_id, int(chunk_count or 0), active_setting.updated_by


async def _prepare(
    factory: async_sessionmaker[AsyncSession],
    active_id: int,
    active_chunks: int,
    active_updated_by: str | None,
    run_tag: str,
) -> DrillResources:
    key, key_hash = generate_admin_key()
    key_name = f"{_KEY_PREFIX}{run_tag}"
    async with factory() as session, session.begin():
        if await active_release_id(session) != active_id:
            raise DrillFailure("active_release_changed_before_setup")
        release = Release(
            status="draft",
            parent_id=active_id,
            note=f"{_RELEASE_PREFIX}{run_tag}",
            created_by="zzdrill-agent",
        )
        session.add(release)
        await session.flush()
        if release.id is None:
            raise DrillFailure("draft_release_id_missing")
        chunk_ids = (
            await session.scalars(
                select(ReleaseChunk.chunk_id).where(ReleaseChunk.release_id == active_id)
            )
        ).all()
        link_ids = (
            await session.scalars(
                select(ReleaseLink.link_id).where(ReleaseLink.release_id == active_id)
            )
        ).all()
        session.add_all(
            ReleaseChunk(release_id=release.id, chunk_id=chunk_id) for chunk_id in chunk_ids
        )
        session.add_all(ReleaseLink(release_id=release.id, link_id=link_id) for link_id in link_ids)
        await session.flush()
        chunks, links = await _release_records(session, release.id)
        release.eval_report = {
            "publishable": True,
            "content_hash": _release_content_hash(chunks, links),
            "drill": _RELEASE_PREFIX + run_tag,
        }
        api_key = ApiKey(
            name=key_name,
            key_hash=key_hash,
            scopes=[
                AdminScope.READ.value,
                AdminScope.PUBLISH.value,
                AdminScope.KEYS.value,
            ],
        )
        session.add(api_key)
        await session.flush()
        return DrillResources(
            run_tag=run_tag,
            active_release_id=active_id,
            active_chunk_count=active_chunks,
            active_updated_by=active_updated_by,
            release_id=release.id,
            key_id=api_key.id,
            key_name=key_name,
            raw_key=key,
        )


def _trace_id(response: object) -> UUID:
    headers = getattr(response, "headers", {})
    value = headers.get("X-Request-ID")
    if not isinstance(value, str):
        raise DrillFailure("request_id_missing")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DrillFailure("request_id_invalid") from exc


def _exercise_routes(
    settings: Settings,
    resources: DrillResources,
    trace_ids: set[UUID],
) -> None:
    application = create_app(settings)
    with TestClient(application) as client:
        headers = {"Authorization": f"Bearer {resources.raw_key}"}
        publish = client.post(
            f"/admin/v1/releases/{resources.release_id}/publish",
            headers={**headers, "Idempotency-Key": resources.publish_key},
        )
        trace_ids.add(_trace_id(publish))
        if publish.status_code != 200:
            raise DrillFailure(f"publish_http_{publish.status_code}")
        if application.state.active_snapshot.release_id != resources.release_id:
            raise DrillFailure("published_snapshot_not_loaded")

        rollback = client.post(
            f"/admin/v1/releases/{resources.active_release_id}/rollback",
            headers={**headers, "Idempotency-Key": resources.rollback_key},
        )
        trace_ids.add(_trace_id(rollback))
        if rollback.status_code != 200:
            raise DrillFailure(f"rollback_http_{rollback.status_code}")
        if application.state.active_snapshot.release_id != resources.active_release_id:
            raise DrillFailure("rollback_snapshot_not_loaded")

        revoke = client.delete(
            f"/admin/v1/api-keys/{resources.key_id}",
            headers=headers,
        )
        trace_ids.add(_trace_id(revoke))
        if revoke.status_code != 200:
            raise DrillFailure(f"key_revoke_http_{revoke.status_code}")


def _idempotency_hash(key_id: UUID, raw_key: str) -> str:
    return hashlib.sha256(f"{key_id}:{raw_key}".encode()).hexdigest()


async def _cleanup(
    factory: async_sessionmaker[AsyncSession],
    resources: DrillResources,
    trace_ids: set[UUID],
) -> None:
    idempotency_hashes = {
        _idempotency_hash(resources.key_id, resources.publish_key),
        _idempotency_hash(resources.key_id, resources.rollback_key),
    }
    async with factory() as session, session.begin():
        setting = await session.get(Setting, "active_release_id")
        if setting is None:
            raise DrillFailure("active_release_setting_missing_during_cleanup")
        current_id = await active_release_id(session)
        if current_id == resources.release_id:
            setting.value = {"value": resources.active_release_id}
            setting.updated_by = resources.active_updated_by
        elif current_id == resources.active_release_id and setting.updated_by == resources.key_name:
            setting.updated_by = resources.active_updated_by

        release = await session.get(Release, resources.release_id)
        if release is None:
            raise DrillFailure("drill_release_missing_during_cleanup")
        release.status = "archived"
        await session.execute(
            delete(ReleaseChunk).where(ReleaseChunk.release_id == resources.release_id)
        )
        await session.execute(
            delete(ReleaseLink).where(ReleaseLink.release_id == resources.release_id)
        )

        api_key = await session.get(ApiKey, resources.key_id)
        if api_key is None:
            raise DrillFailure("temporary_key_missing_during_cleanup")
        api_key.revoked_at = api_key.revoked_at or datetime.now(UTC)

        await session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.key_hash.in_(idempotency_hashes))
        )
        if trace_ids:
            traces = (
                await session.scalars(select(Trace).where(Trace.trace_id.in_(trace_ids)))
            ).all()
            for trace in traces:
                trace.flags = list(dict.fromkeys([*(trace.flags or []), _TRACE_FLAG]))

    await _verify_run(factory, resources, trace_ids)


async def _verify_run(
    factory: async_sessionmaker[AsyncSession],
    resources: DrillResources,
    trace_ids: set[UUID],
) -> None:
    async with factory() as session:
        active_id = await active_release_id(session)
        if active_id != resources.active_release_id:
            raise DrillFailure("active_release_not_restored")
        active_release = await session.get(Release, resources.active_release_id)
        drill_release = await session.get(Release, resources.release_id)
        active_setting = await session.get(Setting, "active_release_id")
        api_key = await session.get(ApiKey, resources.key_id)
        if active_release is None or active_release.status != "published":
            raise DrillFailure("baseline_release_not_published")
        if drill_release is None or drill_release.status != "archived":
            raise DrillFailure("drill_release_not_archived")
        if api_key is None or api_key.revoked_at is None:
            raise DrillFailure("temporary_key_not_revoked")
        if active_setting is None or active_setting.updated_by != resources.active_updated_by:
            raise DrillFailure("active_release_setting_metadata_changed")

        chunk_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == active_id)
        )
        active_drill_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(
                ReleaseChunk.release_id == active_id,
                Chunk.doc_key.startswith("zzdrill-"),
            )
        )
        drafts = await session.scalar(
            select(func.count()).select_from(Release).where(Release.status == "draft")
        )
        draft_chunks = await session.scalar(
            select(func.count())
            .select_from(ReleaseChunk)
            .where(ReleaseChunk.release_id == resources.release_id)
        )
        if int(chunk_count or 0) != resources.active_chunk_count:
            raise DrillFailure("baseline_chunk_count_changed")
        if active_drill_count or drafts or draft_chunks:
            raise DrillFailure("drill_content_not_archived")

        marked_traces = set(
            (
                await session.scalars(
                    select(Trace.trace_id).where(
                        Trace.trace_id.in_(trace_ids),
                        Trace.flags.any(_TRACE_FLAG),
                    )
                )
            ).all()
        )
        if marked_traces != trace_ids:
            raise DrillFailure("drill_traces_missing_or_unmarked")
        actions = {
            (action, target)
            for action, target in (
                await session.execute(
                    select(AuditLog.action, AuditLog.target).where(AuditLog.trace_id.in_(trace_ids))
                )
            ).all()
        }
        expected = {
            ("release.publish", str(resources.release_id)),
            ("release.rollback", str(resources.active_release_id)),
            ("api_key.revoke", resources.key_name),
        }
        if not expected <= actions:
            raise DrillFailure("publish_rollback_audit_missing")


async def _verify_latest(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    active_id, active_chunks = await _current_release(factory)
    async with factory() as session:
        drill = await session.scalar(
            select(Release)
            .where(
                Release.status == "archived",
                Release.note.startswith(_RELEASE_PREFIX),
            )
            .order_by(Release.id.desc())
            .limit(1)
        )
        if drill is None or drill.parent_id != active_id or drill.note is None:
            raise DrillFailure("archived_publish_rollback_drill_missing")
        run_tag = drill.note.removeprefix(_RELEASE_PREFIX)
        api_key = await session.scalar(
            select(ApiKey).where(ApiKey.name == f"{_KEY_PREFIX}{run_tag}")
        )
        if api_key is None or api_key.revoked_at is None:
            raise DrillFailure("publish_rollback_key_not_revoked")
        unrevoked_keys = await session.scalar(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.name.startswith("zzdrill-"), ApiKey.revoked_at.is_(None))
        )
        if unrevoked_keys:
            raise DrillFailure("unrevoked_drill_key_exists")
        live_overrides = await session.scalar(
            select(func.count())
            .select_from(Setting)
            .where(Setting.key.in_({"KILL_SWITCH", "ROLLOUT_PERCENT", "MAINTENANCE_MESSAGE"}))
        )
        if live_overrides:
            raise DrillFailure("live_setting_override_exists")
        drill_links = await session.scalar(
            select(func.count()).select_from(ReleaseLink).where(ReleaseLink.release_id == drill.id)
        )
        if (
            await session.scalar(
                select(func.count())
                .select_from(ReleaseChunk)
                .where(ReleaseChunk.release_id == drill.id)
            )
            or drill_links
        ):
            raise DrillFailure("archived_drill_release_has_content")
        trace_ids = (
            await session.scalars(select(Trace.trace_id).where(Trace.flags.any(_TRACE_FLAG)))
        ).all()
        actions = {
            (action, target)
            for action, target in (
                await session.execute(
                    select(AuditLog.action, AuditLog.target).where(AuditLog.trace_id.in_(trace_ids))
                )
            ).all()
        }
        expected = {
            ("release.publish", str(drill.id)),
            ("release.rollback", str(active_id)),
            ("api_key.revoke", f"{_KEY_PREFIX}{run_tag}"),
        }
        if not trace_ids or not expected <= actions:
            raise DrillFailure("publish_rollback_audit_missing")
    return active_id, active_chunks


async def _current_release(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with factory() as session:
        active_id = await active_release_id(session)
        if active_id is None:
            raise DrillFailure("active_release_missing")
        release = await session.get(Release, active_id)
        if release is None or release.status != "published":
            raise DrillFailure("active_release_not_published")
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == active_id)
        )
        active_drill_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(
                ReleaseChunk.release_id == active_id,
                Chunk.doc_key.startswith("zzdrill-"),
            )
        )
        drafts = await session.scalar(
            select(func.count()).select_from(Release).where(Release.status == "draft")
        )
        if active_drill_count or drafts:
            raise DrillFailure("active_drill_content_or_open_draft")
        return active_id, int(chunk_count or 0)


async def run_drill(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> int:
    resources: DrillResources | None = None
    trace_ids: set[UUID] = set()
    failure: str | None = None
    try:
        active_id, active_chunks, active_updated_by = await _baseline(factory)
        resources = await _prepare(
            factory,
            active_id,
            active_chunks,
            active_updated_by,
            uuid4().hex,
        )
        _exercise_routes(settings, resources, trace_ids)
    except Exception as exc:
        failure = type(exc).__name__
    finally:
        if resources is not None:
            try:
                await _cleanup(factory, resources, trace_ids)
            except Exception as exc:
                failure = failure or f"cleanup_{type(exc).__name__}"

    if failure:
        print(f"DRILL-6 FAIL\t{failure}")
        return 1
    print("DRILL-6 PASS\tpublish, rollback, archive, key revoke, and cleanup")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.env == "prod":
        print("DRILL-6 FAIL\trefusing to run drills with ENV=prod")
        return 1
    engine = create_database_engine(settings)
    if engine is None:
        print("DRILL-6 FAIL\tDATABASE_URL missing")
        return 1
    factory = create_session_factory(engine)
    try:
        if args.verify:
            active_id, chunks = await _verify_latest(factory)
            print(
                f"DRILL-6 PASS\tverified archived drill; active release {active_id}, "
                f"{chunks} chunks"
            )
            return 0
        return await run_drill(settings, factory)
    except DrillFailure as exc:
        print(f"DRILL-6 FAIL\t{exc}")
        return 1
    except SQLAlchemyError as exc:
        print(f"DRILL-6 FAIL\tdatabase_{type(exc).__name__}")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
