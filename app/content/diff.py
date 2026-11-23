from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.content.models import ContentChunk


@dataclass(frozen=True, slots=True)
class ExistingChunk:
    content_hash: str
    origin: str


@dataclass(frozen=True, slots=True)
class ContentDiff:
    added: tuple[ContentChunk, ...]
    changed: tuple[ContentChunk, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[str, ...]
    suppressed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiffSafety:
    allowed: bool
    removal_percent: float
    count_swing_percent: float
    violations: tuple[str, ...]


def diff_chunks(
    existing: Mapping[str, ExistingChunk],
    incoming: Sequence[ContentChunk],
    suppressions: set[str],
) -> ContentDiff:
    added: list[ContentChunk] = []
    changed: list[ContentChunk] = []
    unchanged: list[str] = []
    conflicts: list[str] = []
    suppressed: list[str] = []
    incoming_keys = {chunk.chunk_key for chunk in incoming if chunk.chunk_key not in suppressions}

    for chunk in incoming:
        if chunk.chunk_key in suppressions:
            suppressed.append(chunk.chunk_key)
            continue
        current = existing.get(chunk.chunk_key)
        if current is None:
            added.append(chunk)
            continue
        if current.origin == "manual" and current.content_hash != chunk.content_hash:
            conflicts.append(chunk.chunk_key)
            continue
        if current.content_hash == chunk.content_hash:
            unchanged.append(chunk.chunk_key)
            continue
        changed.append(chunk)

    removed = [
        key
        for key, current in existing.items()
        if current.origin != "manual" and key not in incoming_keys
    ]
    return ContentDiff(
        added=tuple(added),
        changed=tuple(changed),
        removed=tuple(sorted(removed)),
        unchanged=tuple(sorted(unchanged)),
        conflicts=tuple(sorted(conflicts)),
        suppressed=tuple(sorted(suppressed)),
    )


def check_diff_safety(
    existing_count: int,
    incoming_count: int,
    removal_count: int,
    *,
    max_removal_percent: int,
    max_count_swing_percent: int,
    force: bool = False,
) -> DiffSafety:
    denominator = max(existing_count, 1)
    removal_percent = removal_count / denominator * 100 if existing_count else 0
    count_swing_percent = (
        abs(incoming_count - existing_count) / denominator * 100 if existing_count else 0
    )
    violations: list[str] = []
    if removal_percent > max_removal_percent:
        violations.append("removal_limit_exceeded")
    if count_swing_percent > max_count_swing_percent:
        violations.append("count_swing_limit_exceeded")
    return DiffSafety(
        allowed=force or not violations,
        removal_percent=removal_percent,
        count_swing_percent=count_swing_percent,
        violations=tuple(violations),
    )
