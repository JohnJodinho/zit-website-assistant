from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyRecord
from app.security.keys import AdminPrincipal

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_RETENTION = timedelta(hours=24)
Mutation = Callable[[], Awaitable[dict[str, Any]]]


async def execute_idempotently(
    session: AsyncSession,
    request: Request,
    principal: AdminPrincipal,
    payload: object,
    mutation: Mutation,
) -> dict[str, Any]:
    raw_key = request.headers.get("Idempotency-Key", "")
    if not _KEY_PATTERN.fullmatch(raw_key):
        raise HTTPException(status_code=400, detail="invalid_idempotency_key")

    now = datetime.now(UTC)
    key_hash = hashlib.sha256(f"{principal.id}:{raw_key}".encode()).hexdigest()
    request_hash = _payload_hash(payload)
    route = request.url.path
    async with session.begin():
        existing = await session.scalar(
            select(IdempotencyRecord)
            .where(IdempotencyRecord.key_hash == key_hash)
            .with_for_update()
        )
        if existing is not None and existing.expires_at > now:
            if (
                existing.actor_id != principal.id
                or existing.method != request.method
                or existing.route != route
                or existing.request_hash != request_hash
            ):
                raise HTTPException(status_code=409, detail="idempotency_key_reused")
            if not isinstance(existing.response, dict):
                raise RuntimeError("Stored idempotency response is invalid")
            return existing.response
        if existing is not None:
            await session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.key_hash == key_hash)
            )

        await session.execute(
            insert(IdempotencyRecord)
            .values(
                key_hash=key_hash,
                actor_id=principal.id,
                method=request.method,
                route=route,
                request_hash=request_hash,
                response={"state": "processing"},
                expires_at=now + _RETENTION,
            )
            .on_conflict_do_nothing(index_elements=[IdempotencyRecord.key_hash])
        )
        record = await session.scalar(
            select(IdempotencyRecord)
            .where(IdempotencyRecord.key_hash == key_hash)
            .with_for_update()
        )
        if record is None:
            raise RuntimeError("Unable to claim idempotency key")
        if record.response != {"state": "processing"}:
            if record.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="idempotency_key_reused")
            if not isinstance(record.response, dict):
                raise RuntimeError("Stored idempotency response is invalid")
            return record.response

        response = jsonable_encoder(await mutation())
        if not isinstance(response, dict):
            raise TypeError("Idempotent mutations must return an object")
        record.response = response
        return response


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
