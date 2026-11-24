from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = monotonic()
        events = self._events[key]
        while events and now - events[0] >= window_seconds:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        if len(self._events) > 10_000:
            self._remove_expired_buckets(now, window_seconds)
            if len(self._events) > 10_000:
                events.pop()
                return False
        return True

    def _remove_expired_buckets(self, now: float, window_seconds: float) -> None:
        for key, events in list(self._events.items()):
            while events and now - events[0] >= window_seconds:
                events.popleft()
            if not events:
                del self._events[key]
