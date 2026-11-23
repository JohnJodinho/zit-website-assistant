from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey
from app.db.session import get_db_session
from app.embeddings.client import BgeEmbeddingClient
from app.security.keys import AdminPrincipal, AdminScope, hash_admin_key


async def get_admin_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> AdminPrincipal:
    settings = request.app.state.settings
    if not _is_admin_ip_allowed(request, settings.allowed_admin_networks):
        raise HTTPException(status_code=403, detail="admin_ip_not_allowed")
    if authorization is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    scheme, separator, raw_key = authorization.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not separator
        or not raw_key.startswith("zit_")
        or len(raw_key) > 100
    ):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    candidate_hash = hash_admin_key(raw_key)
    api_key = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == candidate_hash, ApiKey.revoked_at.is_(None))
    )
    if api_key is None or not hmac.compare_digest(api_key.key_hash, candidate_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    api_key.last_used_at = datetime.now(UTC)
    await session.commit()
    return AdminPrincipal(api_key.id, api_key.name, frozenset(api_key.scopes))


def _is_admin_ip_allowed(request: Request, allowed_networks: tuple[str, ...]) -> bool:
    if not allowed_networks:
        return True
    if request.client is None:
        return False
    try:
        client_ip = ip_address(request.client.host)
    except ValueError:
        return False
    return any(client_ip in ip_network(network, strict=False) for network in allowed_networks)


def require_scope(
    scope: AdminScope,
) -> Callable[..., Awaitable[AdminPrincipal]]:
    async def dependency(
        principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    ) -> AdminPrincipal:
        if scope.value not in principal.scopes:
            raise HTTPException(status_code=403, detail="insufficient_scope")
        return principal

    return dependency


def get_embedding_client(request: Request) -> BgeEmbeddingClient:
    settings = request.app.state.settings
    if settings.zit_api_key is None:
        raise HTTPException(status_code=503, detail="embedding_provider_not_configured")
    client = getattr(request.app.state, "embedding_client", None)
    if client is None:
        client = BgeEmbeddingClient(settings)
        request.app.state.embedding_client = client
    return client
