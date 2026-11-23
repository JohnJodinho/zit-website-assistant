from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class ModelCounter:
    minute_requests: list[tuple[float, int]]
    minute_tokens: list[tuple[float, int]]
    daily_requests: list[tuple[float, int]]
    failures: int = 0
    open_until: float = 0.0


class QuotaManager:
    def __init__(self) -> None:
        self._counters: dict[str, ModelCounter] = {}

    def eligible(
        self,
        model_id: str,
        *,
        rpm: int | None,
        rpd: int | None,
        tpm: int | None,
        tpd: int | None,
        reserve_tokens: int,
        minute_safety: float,
        daily_safety: float,
    ) -> bool:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], []))
        now = monotonic()
        if now < counter.open_until:
            return False
        minute_requests = sum(count for at, count in counter.minute_requests if now - at <= 60)
        minute_tokens = sum(count for at, count in counter.minute_tokens if now - at <= 60)
        daily_requests = sum(count for at, count in counter.daily_requests if now - at <= 86400)
        if rpm is not None and minute_requests + 1 > rpm * minute_safety:
            return False
        if rpd is not None and daily_requests + 1 > rpd * daily_safety:
            return False
        if tpm is not None and minute_tokens + reserve_tokens > tpm * minute_safety:
            return False
        return not (tpd is not None and minute_tokens + reserve_tokens > tpd * daily_safety)

    def reserve(self, model_id: str, tokens: int) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], []))
        now = monotonic()
        counter.minute_requests.append((now, 1))
        counter.minute_tokens.append((now, tokens))
        counter.daily_requests.append((now, 1))

    def correct(self, model_id: str, reserved: int, actual: int) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], []))
        now = monotonic()
        delta = actual - reserved
        if delta:
            counter.minute_tokens.append((now, delta))

    def record_failure(self, model_id: str, open_seconds: float) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], []))
        counter.failures += 1
        if counter.failures >= 3:
            counter.open_until = monotonic() + open_seconds

    def record_success(self, model_id: str) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], []))
        counter.failures = 0
