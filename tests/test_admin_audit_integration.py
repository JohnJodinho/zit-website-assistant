from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from app.config import Settings, get_settings
from app.db.models import ApiKey, AuditLog, ErrorEvent, Span, Trace
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.security.keys import AdminScope, generate_admin_key, hash_admin_key
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(
    not os.environ.get("PHASE1_TEST_DATABASE_URL"),
    reason="set PHASE1_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


def test_admin_key_changes_are_audited_and_secrets_are_not_listed() -> None:
    base_settings = get_settings()
    if base_settings.env == "prod":
        pytest.fail("Admin integration tests must not run with ENV=prod")

    database_url = os.environ["PHASE1_TEST_DATABASE_URL"]
    settings = base_settings.model_copy(
        update={
            "database_url": SecretStr(database_url),
            "database_url_direct": SecretStr(database_url),
        }
    )
    run_id = uuid4().hex
    owner_name = f"phase1-test-owner-{run_id}"
    created_name = f"phase1-test-created-{run_id}"
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
                await session.execute(delete(AuditLog).where(AuditLog.target.in_(names)))
                await session.execute(delete(ApiKey).where(ApiKey.name.in_(names)))
        finally:
            await engine.dispose()

    asyncio.run(cleanup())
