from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.api.admin.routes import ApiKeyCreate
from app.api.deps import get_admin_principal, require_scope
from app.config import Settings
from app.db.models import ApiKey
from app.security.keys import (
    AdminPrincipal,
    AdminScope,
    generate_admin_key,
    hash_admin_key,
    hash_matches,
    is_valid_key_hash,
)
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


def test_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, widget_origins="*")


def test_generated_admin_key_has_a_verifiable_hash() -> None:
    raw_key, digest = generate_admin_key()

    assert raw_key.startswith("zit_")
    assert len(digest) == 64
    assert is_valid_key_hash(digest)
    assert hash_admin_key(raw_key) == digest
    assert hash_matches(raw_key, digest)
    assert not hash_matches(raw_key + "x", digest)


def test_api_key_scopes_reject_unknown_or_duplicate_values() -> None:
    assert ApiKeyCreate(name="owner", scopes=["admin:read"]).scopes == ["admin:read"]

    with pytest.raises(ValidationError, match="Unknown API-key scope"):
        ApiKeyCreate(name="owner", scopes=["owner"])

    with pytest.raises(ValidationError, match="Scopes must be unique"):
        ApiKeyCreate(name="owner", scopes=["admin:read", "admin:read"])


async def test_admin_authentication_updates_last_used_and_returns_scopes() -> None:
    raw_key, digest = generate_admin_key()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = ApiKey(
        id=uuid4(),
        name="owner",
        key_hash=digest,
        scopes=[AdminScope.KEYS.value],
    )

    principal = await get_admin_principal(
        _request(),
        session,
        f"Bearer {raw_key}",
    )

    assert principal.name == "owner"
    assert principal.scopes == frozenset({AdminScope.KEYS.value})
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("authorization", [None, "Basic token", "Bearer invalid"])
async def test_admin_authentication_rejects_invalid_credentials(
    authorization: str | None,
) -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(HTTPException) as error:
        await get_admin_principal(_request(), session, authorization)

    assert error.value.status_code == 401
    session.commit.assert_not_awaited()


async def test_admin_scope_rejects_principal_without_required_scope() -> None:
    dependency = require_scope(AdminScope.KEYS)
    principal = AdminPrincipal(uuid4(), "reader", frozenset({AdminScope.READ.value}))

    with pytest.raises(HTTPException) as error:
        await dependency(principal)

    assert error.value.status_code == 403


def _request() -> Request:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None)
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "app": app,
        }
    )
