from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import monotonic

_UNKNOWN_RPM_CAP = 10
_UNKNOWN_RPD_CAP = 100
_UNKNOWN_TPM_CAP = 4_000
_UNKNOWN_TPD_CAP = 40_000


@dataclass
class ModelCounter:
    minute_requests: list[tuple[float, int]]
    minute_tokens: list[tuple[float, int]]
    daily_requests: list[tuple[date, int]]
    daily_tokens: list[tuple[date, int]]
    failures: int = 0
    open_until: float = 0.0


@dataclass(frozen=True, slots=True)
class QuotaRecord:
    model_id: str
    started_at: datetime
    status: str
    tokens_in: int | None
    tokens_out: int | None
    estimated_input_tokens: int | None
    reserved_output_tokens: int | None


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
        counter = self._counters.setdefault(model_id, ModelCounter([], [], [], []))
        now = monotonic()
        if now < counter.open_until:
            return False
        today = datetime.now(UTC).date()
        counter.minute_requests = [item for item in counter.minute_requests if now - item[0] <= 60]
        counter.minute_tokens = [item for item in counter.minute_tokens if now - item[0] <= 60]
        counter.daily_requests = [item for item in counter.daily_requests if item[0] == today]
        counter.daily_tokens = [item for item in counter.daily_tokens if item[0] == today]
        minute_requests = sum(count for at, count in counter.minute_requests if now - at <= 60)
        minute_tokens = sum(count for at, count in counter.minute_tokens if now - at <= 60)
        daily_requests = sum(count for _, count in counter.daily_requests)
        daily_tokens = sum(count for _, count in counter.daily_tokens)
        if minute_requests + 1 > _limit(rpm, _UNKNOWN_RPM_CAP) * minute_safety:
            return False
        if daily_requests + 1 > _limit(rpd, _UNKNOWN_RPD_CAP) * daily_safety:
            return False
        if minute_tokens + reserve_tokens > _limit(tpm, _UNKNOWN_TPM_CAP) * minute_safety:
            return False
        return daily_tokens + reserve_tokens <= _limit(tpd, _UNKNOWN_TPD_CAP) * daily_safety

    def reserve(self, model_id: str, tokens: int) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], [], []))
        now = monotonic()
        today = datetime.now(UTC).date()
        counter.minute_requests.append((now, 1))
        counter.minute_tokens.append((now, tokens))
        counter.daily_requests.append((today, 1))
        counter.daily_tokens.append((today, tokens))

    def correct(self, model_id: str, reserved: int, actual: int) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], [], []))
        now = monotonic()
        today = datetime.now(UTC).date()
        delta = actual - reserved
        if delta:
            counter.minute_tokens.append((now, delta))
            counter.daily_tokens.append((today, delta))

    def record_failure(
        self,
        model_id: str,
        open_seconds: float,
        threshold: int = 3,
    ) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], [], []))
        counter.failures += 1
        if counter.failures >= threshold:
            counter.open_until = monotonic() + open_seconds

    def record_success(self, model_id: str) -> None:
        counter = self._counters.setdefault(model_id, ModelCounter([], [], [], []))
        counter.failures = 0

    def rebuild(
        self,
        records: Iterable[QuotaRecord],
        *,
        breaker_failures: int,
        breaker_open_seconds: float,
    ) -> None:
        now = monotonic()
        now_utc = datetime.now(UTC)
        sorted_records = sorted(records, key=lambda record: record.started_at)
        latest_failure: dict[str, datetime] = {}
        failures: dict[str, int] = {}
        for record in sorted_records:
            started_at = _as_utc(record.started_at)
            age = max(0.0, (now_utc - started_at).total_seconds())
            tokens = _record_tokens(record)
            counter = self._counters.setdefault(
                record.model_id,
                ModelCounter([], [], [], []),
            )
            if started_at.date() == now_utc.date():
                counter.daily_requests.append((started_at.date(), 1))
                counter.daily_tokens.append((started_at.date(), tokens))
            if age <= 60:
                counter.minute_requests.append((now - age, 1))
                counter.minute_tokens.append((now - age, tokens))
            if record.status in {"error", "partial"}:
                failures[record.model_id] = failures.get(record.model_id, 0) + 1
                latest_failure[record.model_id] = started_at
            elif record.status == "ok":
                failures[record.model_id] = 0
                latest_failure.pop(record.model_id, None)

        for model_id, count in failures.items():
            counter = self._counters[model_id]
            counter.failures = count
            failed_at = latest_failure.get(model_id)
            if count >= breaker_failures and failed_at is not None:
                age = max(0.0, (now_utc - failed_at).total_seconds())
                remaining = breaker_open_seconds - age
                if remaining > 0:
                    counter.open_until = now + remaining


def _limit(value: int | None, fallback: int) -> int:
    return value if value is not None else fallback


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _record_tokens(record: QuotaRecord) -> int:
    if record.tokens_in is not None and record.tokens_out is not None:
        return record.tokens_in + record.tokens_out
    return (record.estimated_input_tokens or 0) + (record.reserved_output_tokens or 0)
