from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

_MAX_ENTRIES = 512
_MIN_SIMILARITY = 0.97


@dataclass(frozen=True, slots=True)
class CachedAnswer:
    answer: str
    match: str


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: str
    release_id: int
    vector: tuple[float, ...] | None
    hit_keys: frozenset[str]
    expires_at: float


class AnswerCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def get(
        self,
        question: str,
        vector: tuple[float, ...] | None,
        release_id: int,
        hit_keys: frozenset[str],
    ) -> CachedAnswer | None:
        now = monotonic()
        self._discard_expired(now)
        exact_key = _question_key(question)
        exact = self._entries.get(exact_key)
        if exact is not None and exact.release_id == release_id and exact.hit_keys == hit_keys:
            self._entries.move_to_end(exact_key)
            return CachedAnswer(exact.answer, "cache_exact")
        if vector is None:
            return None
        for key, entry in reversed(self._entries.items()):
            if (
                entry.release_id != release_id
                or not _similar_context(entry.hit_keys, hit_keys)
                or entry.vector is None
            ):
                continue
            if _cosine(vector, entry.vector) >= _MIN_SIMILARITY:
                self._entries.move_to_end(key)
                return CachedAnswer(entry.answer, "cache_semantic")
        return None

    def put(
        self,
        question: str,
        answer: str,
        release_id: int,
        vector: tuple[float, ...] | None,
        hit_keys: frozenset[str],
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds < 1:
            return
        key = _question_key(question)
        self._entries[key] = _Entry(
            answer=answer,
            release_id=release_id,
            vector=vector,
            hit_keys=hit_keys,
            expires_at=monotonic() + ttl_seconds,
        )
        self._entries.move_to_end(key)
        self._discard_expired(monotonic())
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def _discard_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]


def _question_key(question: str) -> str:
    normalized = " ".join(question.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _similar_context(left: frozenset[str], right: frozenset[str]) -> bool:
    if not left or not right:
        return False
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union >= 0.8


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
