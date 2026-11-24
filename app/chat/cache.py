from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class CachedAnswer:
    answer: str
    path: str


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: str
    release_id: int
    expires_at: float


class AnswerCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def get(
        self,
        question: str,
        release_id: int,
    ) -> CachedAnswer | None:
        now = monotonic()
        self._discard_expired(now)
        exact_key = _question_key(question)
        exact = self._entries.get(exact_key)
        if exact is not None and exact.release_id == release_id:
            self._entries.move_to_end(exact_key)
            return CachedAnswer(exact.answer, "cache_exact")
        return None

    def put(
        self,
        question: str,
        answer: str,
        release_id: int,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds < 1:
            return
        key = _question_key(question)
        self._entries[key] = _Entry(
            answer=answer,
            release_id=release_id,
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
