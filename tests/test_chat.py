from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.chat.models import eligible_models, parse_llm_models
from app.chat.pii import mask_pii
from app.chat.quota import QuotaManager, QuotaRecord
from app.chat.sessions import create_session_token, hash_session_token


def test_pii_masking_removes_personal_data() -> None:
    text = "My name is Ada. Email ada@example.com, phone +2348012345678, NIN 12345678901."
    masked, found = mask_pii(text)
    assert "ada@example.com" not in masked
    assert "+2348012345678" not in masked
    assert "12345678901" not in masked
    assert {"email", "phone", "nin_bvn", "name"} <= set(found)


def test_free_only_model_flags() -> None:
    raw = (
        '[{"model":"openai/gpt-oss-20b","provider":"groq","tier":1,'
        '"enabled":true,"free_confirmed":true,"rpm":30,"rpd":1000,"tpm":8000,"tpd":200000},'
        '{"model":"disabled","provider":"gemini","tier":2,"enabled":true,'
        '"free_confirmed":false,"rpm":5,"rpd":20,"tpm":250000,"tpd":20000}]'
    )
    models = parse_llm_models(raw)
    assert len(models) == 2
    assert [model.model_id for model in eligible_models(raw)] == ["openai/gpt-oss-20b"]


def test_quota_reservation_and_breaker() -> None:
    quota = QuotaManager()
    assert quota.eligible(
        "model",
        rpm=30,
        rpd=100,
        tpm=8000,
        tpd=200000,
        reserve_tokens=100,
        minute_safety=0.9,
        daily_safety=0.95,
    )
    quota.reserve("model", 100)
    quota.record_failure("model", 30)
    quota.record_failure("model", 30)
    quota.record_failure("model", 30)
    assert not quota.eligible(
        "model",
        rpm=30,
        rpd=100,
        tpm=8000,
        tpd=200000,
        reserve_tokens=100,
        minute_safety=0.9,
        daily_safety=0.95,
    )


def test_daily_token_limit_survives_the_minute_window(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr("app.chat.quota.monotonic", lambda: now[0])
    quota = QuotaManager()
    quota.reserve("model", 900)
    now[0] = 61.0

    assert not quota.eligible(
        "model",
        rpm=30,
        rpd=100,
        tpm=8000,
        tpd=1000,
        reserve_tokens=101,
        minute_safety=1.0,
        daily_safety=1.0,
    )

    quota.correct("model", reserved=900, actual=600)

    assert quota.eligible(
        "model",
        rpm=30,
        rpd=100,
        tpm=8000,
        tpd=1000,
        reserve_tokens=400,
        minute_safety=1.0,
        daily_safety=1.0,
    )


def test_unknown_quota_uses_a_conservative_request_cap() -> None:
    quota = QuotaManager()
    for _ in range(10):
        quota.reserve("model", 10)

    assert not quota.eligible(
        "model",
        rpm=None,
        rpd=None,
        tpm=None,
        tpd=None,
        reserve_tokens=10,
        minute_safety=1.0,
        daily_safety=1.0,
    )


def test_session_token_is_hmac_hashed() -> None:
    token = create_session_token()
    assert len(token) >= 32
    assert hash_session_token(token, "pepper") != token


def test_quota_rebuild_restores_recent_usage_and_open_breakers() -> None:
    now = datetime.now(UTC)
    records = [
        QuotaRecord("used", now - timedelta(seconds=10), "ok", 60, 40, 25, 300),
        *(
            QuotaRecord(
                "broken",
                now - timedelta(seconds=3 - index),
                "error",
                None,
                None,
                25,
                300,
            )
            for index in range(3)
        ),
    ]
    quota = QuotaManager()

    quota.rebuild(records, breaker_failures=3, breaker_open_seconds=30)

    assert not quota.eligible(
        "used",
        rpm=1,
        rpd=100,
        tpm=8000,
        tpd=1000,
        reserve_tokens=1,
        minute_safety=1.0,
        daily_safety=1.0,
    )
    assert not quota.eligible(
        "broken",
        rpm=30,
        rpd=100,
        tpm=8000,
        tpd=1000,
        reserve_tokens=1,
        minute_safety=1.0,
        daily_safety=1.0,
    )
