from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SessionRecord
from app.obs.logging import get_logger


async def run_retention(session: AsyncSession, retention_days: int = 30) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(delete(SessionRecord).where(SessionRecord.last_seen_at < cutoff))
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def next_retention_run(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("retention scheduler requires a timezone-aware clock")
    current = now.astimezone(UTC)
    scheduled = current.replace(hour=2, minute=0, second=0, microsecond=0)
    return scheduled if scheduled > current else scheduled + timedelta(days=1)


async def run_nightly_retention(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    logger = get_logger("ops.retention")
    while True:
        current = clock().astimezone(UTC)
        scheduled = next_retention_run(current)
        await sleep((scheduled - current).total_seconds())
        try:
            async with session_factory() as session:
                deleted = await run_retention(session)
            logger.info("retention_completed", deleted_sessions=deleted)
        except SQLAlchemyError as exc:
            logger.error("retention_failed", error_type=type(exc).__name__)
