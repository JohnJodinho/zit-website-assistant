from __future__ import annotations

from app.chat.models import eligible_models, parse_llm_models
from app.chat.pii import mask_pii
from app.chat.quota import QuotaManager
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


def test_session_token_is_hmac_hashed() -> None:
    token = create_session_token()
    assert len(token) >= 32
    assert hash_session_token(token, "pepper") != token
