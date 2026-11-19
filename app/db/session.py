from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def build_async_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("DATABASE_URL must use PostgreSQL")
    if "sslmode" in url.query:
        url = url.difference_update_query(["sslmode"])
    return url


def build_connect_args(url: URL, ssl_root_cert: Path | None = None) -> dict[str, Any]:
    connect_args: dict[str, Any] = {}
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        sslmode = url.query.get("sslmode")
        is_supabase = (url.host or "").endswith((".supabase.co", ".pooler.supabase.com"))
        if ssl_root_cert is not None:
            connect_args["ssl"] = ssl.create_default_context(cafile=str(ssl_root_cert))
        elif sslmode == "require" or (sslmode is None and is_supabase):
            connect_args["ssl"] = "require"
        elif sslmode in {"verify-ca", "verify-full"}:
            connect_args["ssl"] = sslmode
        elif sslmode is not None:
            raise ValueError(
                "Remote PostgreSQL connections require sslmode=require or certificate verification"
            )
        else:
            connect_args["ssl"] = ssl.create_default_context()
    if url.port == 6543 and (url.host or "").endswith(".pooler.supabase.com"):
        connect_args["statement_cache_size"] = 0
    return connect_args


def create_database_engine(settings: Settings) -> AsyncEngine | None:
    if settings.database_url is None:
        return None

    raw_url = settings.database_url.get_secret_value()
    url = build_async_url(raw_url)
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=0,
        connect_args=build_connect_args(
            make_url(raw_url),
            settings.database_ssl_root_cert,
        ),
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    async with session_factory() as session:
        yield session
