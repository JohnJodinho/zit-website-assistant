from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from ipaddress import ip_address

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.sessions import create_session_token, hash_session_token, session_expiry
from app.config import Settings
from app.db.models import SessionRecord

_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{40,48}$")


async def create_session_record(
    session: AsyncSession,
    settings: Settings,
    request: Request,
) -> str:
    pepper = _session_pepper(settings)
    token = create_session_token()
    session.add(
        SessionRecord(
            token_hash=hash_session_token(token, pepper),
            ip_hash=_fingerprint(_client_ip(request, settings.trusted_proxy_hops), pepper),
            ua_hash=_fingerprint(request.headers.get("user-agent", ""), pepper),
            last_seen_at=datetime.now(UTC),
            expires_at=session_expiry(settings.session_ttl_minutes, settings.session_max_hours),
            turn_count=0,
            state={},
        )
    )
    await session.commit()
    return token


async def find_session(
    session: AsyncSession,
    settings: Settings,
    token: str,
) -> SessionRecord | None:
    if not _SESSION_TOKEN.fullmatch(token):
        return None
    try:
        token_hash = hash_session_token(token, _session_pepper(settings))
    except UnicodeEncodeError:
        return None
    record = await session.scalar(
        select(SessionRecord).where(SessionRecord.token_hash == token_hash)
    )
    if record is None or record.expires_at <= datetime.now(UTC):
        return None
    record.last_seen_at = datetime.now(UTC)
    await session.commit()
    return record


def _session_pepper(settings: Settings) -> str:
    if settings.session_pepper is None:
        raise ValueError("SESSION_PEPPER is required for public sessions")
    return settings.session_pepper.get_secret_value()


def _client_ip(request: Request, trusted_hops: int) -> str:
    peer = request.client.host if request.client is not None else ""
    if trusted_hops:
        forwarded = [
            item.strip()
            for item in request.headers.get("x-forwarded-for", "").split(",")
            if item.strip()
        ]
        if len(forwarded) >= trusted_hops:
            peer = forwarded[-trusted_hops]
    try:
        return str(ip_address(peer))
    except ValueError:
        return ""


def rate_limit_key(request: Request, settings: Settings) -> str:
    return (
        _fingerprint(
            _client_ip(request, settings.trusted_proxy_hops),
            _session_pepper(settings),
        )
        or "unknown"
    )


def _fingerprint(value: str, pepper: str) -> str | None:
    if not value:
        return None
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()
