from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import ApiKey, AuditLog
from app.db.session import create_database_engine, create_session_factory


class AdminScope(StrEnum):
    READ = "admin:read"
    WRITE = "admin:write"
    PUBLISH = "admin:publish"
    ETL_RUN = "etl:run"
    KEYS = "admin:keys"


ALL_ADMIN_SCOPES = tuple(scope.value for scope in AdminScope)
KEY_PREFIX = "zit_"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    id: UUID
    name: str
    scopes: frozenset[str]


def generate_admin_key() -> tuple[str, str]:
    raw_key = KEY_PREFIX + secrets.token_urlsafe(40)
    return raw_key, hash_admin_key(raw_key)


def hash_admin_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_matches(raw_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_admin_key(raw_key), stored_hash)


def is_valid_key_hash(value: str) -> bool:
    return bool(_HASH_PATTERN.fullmatch(value))


async def bootstrap_key(
    session_factory: async_sessionmaker[AsyncSession],
    bootstrap_hash: str,
) -> bool:
    if not is_valid_key_hash(bootstrap_hash):
        raise ValueError("ADMIN_BOOTSTRAP_KEY_HASH must be a SHA-256 hex digest")

    async with session_factory() as session, session.begin():
        existing_count = await session.scalar(select(func.count()).select_from(ApiKey))
        if existing_count:
            return False

        key = ApiKey(
            name="owner-bootstrap",
            key_hash=bootstrap_hash,
            scopes=list(ALL_ADMIN_SCOPES),
        )
        session.add(key)
        session.add(
            AuditLog(
                actor="system",
                action="api_key.bootstrap",
                target=key.name,
                before=None,
                after={"name": key.name, "scopes": list(ALL_ADMIN_SCOPES)},
            )
        )
    return True


async def _run_bootstrap(settings: Settings) -> bool:
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required for bootstrap")
    if settings.admin_bootstrap_key_hash is None:
        raise ValueError("ADMIN_BOOTSTRAP_KEY_HASH is required for bootstrap")

    engine = create_database_engine(settings)
    if engine is None:
        raise ValueError("DATABASE_URL is required for bootstrap")
    try:
        return await bootstrap_key(
            create_session_factory(engine),
            settings.admin_bootstrap_key_hash.get_secret_value(),
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.security.keys")
    parser.add_argument("command", choices=("generate", "bootstrap"))
    command = parser.parse_args().command

    if command == "generate":
        raw_key, key_hash = generate_admin_key()
        print(f"ADMIN_KEY={raw_key}")
        print(f"ADMIN_BOOTSTRAP_KEY_HASH={key_hash}")
        return

    created = asyncio.run(_run_bootstrap(get_settings()))
    print(
        "Bootstrap key record created." if created else "An API key already exists; no change made."
    )


if __name__ == "__main__":
    main()
