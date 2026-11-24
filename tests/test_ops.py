from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.db.models import SessionRecord
from app.ops import next_retention_run, run_nightly_retention, run_retention


class FakeSession:
    def __init__(self) -> None:
        self.statement = None
        self.committed = False

    async def execute(self, statement: object) -> SimpleNamespace:
        self.statement = statement
        return SimpleNamespace(rowcount=3)

    async def commit(self) -> None:
        self.committed = True


def test_retention_deletes_only_expired_sessions_and_commits() -> None:
    session = FakeSession()

    deleted = asyncio.run(run_retention(session, retention_days=30))

    assert deleted == 3
    assert session.committed is True
    assert SessionRecord.__tablename__ in str(session.statement)


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (datetime(2026, 1, 1, 1, 59, tzinfo=UTC), datetime(2026, 1, 1, 2, tzinfo=UTC)),
        (datetime(2026, 1, 1, 2, tzinfo=UTC), datetime(2026, 1, 2, 2, tzinfo=UTC)),
    ],
)
def test_retention_is_scheduled_at_next_0200_utc(current, expected) -> None:
    assert next_retention_run(current) == expected


def test_nightly_worker_runs_and_is_cancellable() -> None:
    now = [datetime(2026, 1, 1, 1, 59, 59, tzinfo=UTC)]
    sleeps: list[float] = []
    session = FakeSession()
    session_entries = 0

    class SessionContext:
        async def __aenter__(self) -> FakeSession:
            nonlocal session_entries
            session_entries += 1
            return session

        async def __aexit__(self, *_: object) -> None:
            return None

    class SessionFactory:
        def __call__(self) -> SessionContext:
            return SessionContext()

    async def advance(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            now[0] += timedelta(seconds=seconds)
            return
        raise asyncio.CancelledError

    async def run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await run_nightly_retention(
                SessionFactory(),
                clock=lambda: now[0],
                sleep=advance,
            )

    asyncio.run(run())

    assert sleeps == [1, 24 * 60 * 60]
    assert session_entries == 1
    assert session.committed is True
