from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionRecord


async def run_retention(session: AsyncSession, retention_days: int = 30) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(delete(SessionRecord).where(SessionRecord.last_seen_at < cutoff))
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
