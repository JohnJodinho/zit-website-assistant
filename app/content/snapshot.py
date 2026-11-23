from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.content.repository import active_release_id
from app.db.models import Chunk, Link, Release, ReleaseChunk, ReleaseLink
from app.embeddings.client import BGE_MODEL_ID

_ALLOWED_HOSTS = {"www.zibeh.ng", "zibeh.ng"}


@dataclass(frozen=True, slots=True)
class SnapshotChunk:
    id: str
    chunk_key: str
    doc_key: str
    kind: str
    text: str
    embed_text: str | None
    token_count: int
    metadata: dict[str, object]
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SnapshotLink:
    link_key: str
    kind: str
    label: str
    url: str
    description: str
    aliases: tuple[str, ...]
    priority: int


@dataclass(frozen=True, slots=True)
class ContentSnapshot:
    release_id: int
    chunks: tuple[SnapshotChunk, ...]
    links: tuple[SnapshotLink, ...]
    loaded_at: str


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    valid: bool
    errors: tuple[dict[str, str], ...]
    warnings: tuple[dict[str, str], ...]


def validate_release_content(
    chunks: Sequence[Chunk],
    links: Sequence[Link],
    settings: Settings,
) -> ReleaseCheck:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    active_links = _active_link_index(links, errors)
    chunk_counts = Counter(chunk.chunk_key for chunk in chunks)
    errors.extend(
        {"code": "duplicate_chunk_key", "chunk_key": key}
        for key, count in sorted(chunk_counts.items())
        if count > 1
    )
    if not chunks:
        errors.append({"code": "release_empty"})
    for chunk in chunks:
        errors.extend(_validate_chunk(chunk, active_links, settings))
        _add_review_warning(chunk, warnings)
    errors.extend(_required_link_errors(chunks, active_links))
    return ReleaseCheck(not errors, tuple(errors), tuple(warnings))


async def load_active_snapshot(
    session: AsyncSession,
    settings: Settings,
) -> ContentSnapshot | None:
    release_id = await active_release_id(session)
    if release_id is None:
        return None
    return await load_release_snapshot(session, release_id, settings)


async def load_release_snapshot(
    session: AsyncSession,
    release_id: int,
    settings: Settings,
) -> ContentSnapshot:
    release = await session.get(Release, release_id)
    if release is None or release.status != "published":
        raise ValueError(f"Release {release_id} is not published")
    chunks = (
        await session.scalars(
            select(Chunk)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(ReleaseChunk.release_id == release_id)
        )
    ).all()
    links = (
        await session.scalars(
            select(Link)
            .join(ReleaseLink, ReleaseLink.link_id == Link.id)
            .where(ReleaseLink.release_id == release_id, Link.active.is_(True))
        )
    ).all()
    check = validate_release_content(chunks, links, settings)
    if not check.valid:
        codes = sorted({error["code"] for error in check.errors})
        raise ValueError(f"Release {release_id} failed validation: {', '.join(codes)}")

    snapshot_chunks = tuple(
        SnapshotChunk(
            id=str(chunk.id),
            chunk_key=chunk.chunk_key,
            doc_key=chunk.doc_key,
            kind=chunk.kind,
            text=chunk.text,
            embed_text=chunk.embed_text,
            token_count=chunk.token_count,
            metadata=dict(chunk.metadata_json),
            embedding=tuple(
                float(value) for value in (chunk.embedding if chunk.embedding is not None else ())
            ),
        )
        for chunk in chunks
    )
    snapshot_links = tuple(
        SnapshotLink(
            link_key=link.link_key,
            kind=link.kind,
            label=link.label,
            url=link.url,
            description=link.description,
            aliases=tuple(link.aliases),
            priority=link.priority,
        )
        for link in links
    )
    return ContentSnapshot(
        release_id=release_id,
        chunks=snapshot_chunks,
        links=snapshot_links,
        loaded_at=datetime.now(UTC).isoformat(),
    )


def _allowed_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _active_link_index(
    links: Sequence[Link],
    errors: list[dict[str, str]],
) -> dict[str, Link]:
    active_links: dict[str, Link] = {}
    for link in links:
        if not link.active:
            continue
        if not _allowed_url(link.url):
            errors.append({"code": "invalid_link_url", "link_key": link.link_key})
        if link.link_key in active_links:
            errors.append({"code": "duplicate_link_key", "link_key": link.link_key})
        active_links[link.link_key] = link
    return active_links


def _validate_chunk(
    chunk: Chunk,
    active_links: dict[str, Link],
    settings: Settings,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not chunk.text.strip() or chunk.token_count <= 0:
        errors.append({"code": "chunk_content_invalid", "chunk_key": chunk.chunk_key})
    if chunk.embedding is None:
        errors.append({"code": "embedding_missing", "chunk_key": chunk.chunk_key})
    elif not _valid_embedding(chunk.embedding):
        errors.append({"code": "embedding_invalid", "chunk_key": chunk.chunk_key})
    if chunk.embedding_model != BGE_MODEL_ID:
        errors.append({"code": "embedding_model_mismatch", "chunk_key": chunk.chunk_key})
    if chunk.token_count > settings.chunk_hard_max_tokens:
        errors.append({"code": "chunk_too_long", "chunk_key": chunk.chunk_key})
    errors.extend(_chunk_link_errors(chunk, active_links))
    return errors


def _chunk_link_errors(
    chunk: Chunk,
    active_links: dict[str, Link],
) -> list[dict[str, str]]:
    link_keys = chunk.metadata_json.get("link_keys", [])
    if not isinstance(link_keys, list):
        return [{"code": "invalid_chunk_link_keys", "chunk_key": chunk.chunk_key}]
    return [
        {"code": "unknown_chunk_link_key", "chunk_key": chunk.chunk_key}
        for key in link_keys
        if not isinstance(key, str) or key not in active_links
    ]


def _required_link_errors(
    chunks: Sequence[Chunk],
    active_links: dict[str, Link],
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    course_doc_keys = {chunk.doc_key for chunk in chunks if chunk.doc_key.startswith("course:")}
    for doc_key in course_doc_keys:
        slug = doc_key.removeprefix("course:")
        for key in (f"course:{slug}", f"apply:{slug}"):
            if key not in active_links:
                errors.append({"code": "required_course_link_missing", "doc_key": doc_key})
    if "contact:admissions" not in active_links:
        errors.append({"code": "contact_link_missing"})
    return errors


def _valid_embedding(values: Sequence[float]) -> bool:
    if len(values) != 768 or not all(math.isfinite(value) for value in values):
        return False
    norm = math.sqrt(sum(value * value for value in values))
    return math.isclose(norm, 1.0, rel_tol=0.002, abs_tol=0.002)


def _add_review_warning(chunk: Chunk, warnings: list[dict[str, str]]) -> None:
    faq = chunk.metadata_json.get("faq")
    if not isinstance(faq, dict):
        return
    review_after = faq.get("review_after")
    if not isinstance(review_after, str):
        return
    try:
        due_date = date.fromisoformat(review_after)
    except ValueError:
        warnings.append({"code": "invalid_faq_review_date", "chunk_key": chunk.chunk_key})
        return
    if due_date <= date.today():
        warnings.append({"code": "faq_review_due", "chunk_key": chunk.chunk_key})
