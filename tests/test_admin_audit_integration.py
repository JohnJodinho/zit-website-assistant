from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from app.config import Settings, get_settings
from app.db.models import ApiKey, AuditLog, ErrorEvent, Span, Trace
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.security.keys import AdminScope, generate_admin_key, hash_admin_key
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def test_admin_key_changes_are_audited_and_secrets_are_not_listed() -> None:
    base_settings = get_settings()
    if base_settings.env == "prod":
        pytest.fail("Admin integration tests must not run with ENV=prod")
    if base_settings.database_url is None:
        pytest.fail("DATABASE_URL is required for shared-database integration tests")

    settings = base_settings.model_copy(update={"writer_flush_seconds": 0.01})
    run_id = uuid4().hex
    owner_name = f"zzdrill-agent-drill-temp-{run_id}"
    created_name = f"zzdrill-admin-created-{run_id}"
    owner_key, owner_hash = generate_admin_key()
    request_ids: set[UUID] = set()

    async def insert_owner_key(session: AsyncSession) -> None:
        session.add(
            ApiKey(
                name=owner_name,
                key_hash=owner_hash,
                scopes=[AdminScope.KEYS.value, AdminScope.READ.value],
            )
        )

    _run_database_operation(settings, insert_owner_key)

    try:
        with TestClient(create_app(settings)) as client:
            create_response = client.post(
                "/admin/v1/api-keys",
                headers={"Authorization": f"Bearer {owner_key}"},
                json={"name": created_name, "scopes": [AdminScope.READ.value]},
            )
            request_ids.add(UUID(create_response.headers["X-Request-ID"]))
            assert create_response.status_code == 201
            created_key = create_response.json()["key"]
            created_key_id = create_response.json()["api_key"]["id"]

            list_response = client.get(
                "/admin/v1/api-keys",
                headers={"Authorization": f"Bearer {owner_key}"},
            )
            request_ids.add(UUID(list_response.headers["X-Request-ID"]))
            assert list_response.status_code == 200
            assert created_key not in list_response.text

            broken_responses = (
                client.get(f"/zzdrill-missing-{run_id}"),
                client.get(
                    "/admin/v1/traces/not-a-uuid",
                    headers={"Authorization": f"Bearer {owner_key}"},
                ),
            )
            for response in broken_responses:
                request_ids.add(UUID(response.headers["X-Request-ID"]))
                assert response.status_code in {404, 422}

            for response in broken_responses:
                trace_id = UUID(response.headers["X-Request-ID"])
                trace_detail = _lookup_trace(client, owner_key, trace_id, request_ids)
                assert trace_detail["trace"]["status"] == "error"
                assert trace_detail["spans"]

            revoke_response = client.delete(
                f"/admin/v1/api-keys/{created_key_id}",
                headers={"Authorization": f"Bearer {owner_key}"},
            )
            request_ids.add(UUID(revoke_response.headers["X-Request-ID"]))
            assert revoke_response.status_code == 200

            revoked_key_response = client.get(
                "/admin/v1/traces",
                headers={"Authorization": f"Bearer {created_key}"},
            )
            request_ids.add(UUID(revoked_key_response.headers["X-Request-ID"]))
            assert revoked_key_response.status_code == 401

            audit_response = client.get(
                "/admin/v1/audit?limit=100",
                headers={"Authorization": f"Bearer {owner_key}"},
            )
            request_ids.add(UUID(audit_response.headers["X-Request-ID"]))
            assert audit_response.status_code == 200
            audit_rows = [
                row
                for row in audit_response.json()["items"]
                if row["target"] in {owner_name, created_name}
            ]
            assert {row["action"] for row in audit_rows} == {
                "api_key.create",
                "api_key.revoke",
            }
            assert created_key not in str(audit_rows)

        async def verify_records(session: AsyncSession) -> None:
            traces = (
                await session.scalars(select(Trace).where(Trace.trace_id.in_(request_ids)))
            ).all()
            for trace in traces:
                trace.flags = ["zzdrill-admin-drill"]
            key = await session.scalar(select(ApiKey).where(ApiKey.name == created_name))
            assert key is not None
            assert key.key_hash == hash_admin_key(created_key)
            assert key.revoked_at is not None

            audit_records = (
                await session.scalars(select(AuditLog).where(AuditLog.target == created_name))
            ).all()
            assert {record.action for record in audit_records} == {
                "api_key.create",
                "api_key.revoke",
            }
            assert all(
                created_key not in str((record.before, record.after)) for record in audit_records
            )

        _run_database_operation(settings, verify_records)
    finally:
        _cleanup_test_rows(settings, {owner_name, created_name}, request_ids)


def _lookup_trace(
    client: TestClient,
    owner_key: str,
    trace_id: UUID,
    request_ids: set[UUID],
) -> dict[str, object]:
    for _ in range(40):
        response = client.get(
            f"/admin/v1/traces/{trace_id}",
            headers={"Authorization": f"Bearer {owner_key}"},
        )
        request_ids.add(UUID(response.headers["X-Request-ID"]))
        if response.status_code == 200:
            return response.json()
        if response.status_code != 404:
            pytest.fail(f"Trace lookup failed with status {response.status_code}")
        time.sleep(0.05)
    pytest.fail("Trace was not persisted before the drill deadline")


def _run_database_operation(
    settings: Settings,
    operation: Callable[[AsyncSession], Awaitable[None]],
) -> None:
    async def run() -> None:
        engine = create_database_engine(settings)
        if engine is None:
            raise RuntimeError("PHASE1_TEST_DATABASE_URL is required")
        try:
            async with create_session_factory(engine)() as session:
                await operation(session)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _cleanup_test_rows(settings: Settings, names: set[str], trace_ids: set[UUID]) -> None:
    async def cleanup() -> None:
        engine = create_database_engine(settings)
        if engine is None:
            raise RuntimeError("PHASE1_TEST_DATABASE_URL is required")
        try:
            async with create_session_factory(engine)() as session, session.begin():
                if trace_ids:
                    await session.execute(
                        delete(ErrorEvent).where(ErrorEvent.trace_id.in_(trace_ids))
                    )
                    await session.execute(delete(Span).where(Span.trace_id.in_(trace_ids)))
                    await session.execute(delete(Trace).where(Trace.trace_id.in_(trace_ids)))
                await session.execute(delete(ApiKey).where(ApiKey.name.in_(names)))
        finally:
            await engine.dispose()

    asyncio.run(cleanup())
