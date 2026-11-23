from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db.models import Chunk, Release, ReleaseChunk, Setting
from app.db.session import create_database_engine, create_session_factory
from sqlalchemy import func, select


async def main() -> int:
    settings = get_settings()
    engine = create_database_engine(settings)
    if engine is None:
        print("RELEASE FAIL\tDATABASE_URL missing")
        return 1
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            setting = await session.get(Setting, "active_release_id")
            if setting is None:
                print("RELEASE FAIL\tno active release")
                return 1
            value = setting.value.get("value")
            if type(value) is not int:
                print("RELEASE FAIL\tinvalid active release setting")
                return 1
            release = await session.get(Release, value)
            if release is None or release.status != "published":
                print("RELEASE FAIL\tactive release is not published")
                return 1
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
                .where(ReleaseChunk.release_id == value)
            )
            drill_count = await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
                .where(
                    ReleaseChunk.release_id == value,
                    Chunk.doc_key.startswith("zzdrill-"),
                )
            )
            if int(drill_count or 0) != 0:
                print("RELEASE FAIL\tsynthetic active content")
                return 1
            print(f"RELEASE PASS\t{value}\t{int(chunk_count or 0)}")
            return 0
    except Exception as exc:
        print(f"RELEASE FAIL\t{type(exc).__name__}")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
