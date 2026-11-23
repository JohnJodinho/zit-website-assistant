from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMModel:
    model_id: str
    provider: str
    tier: int
    enabled: bool
    free_confirmed: bool
    rpm: int | None
    rpd: int | None
    tpm: int | None
    tpd: int | None


def parse_llm_models(raw: str) -> tuple[LLMModel, ...]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(values, list):
        return ()
    models: list[LLMModel] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        model_id = value.get("model")
        provider = value.get("provider")
        tier = value.get("tier")
        if not isinstance(model_id, str) or not isinstance(provider, str):
            continue
        if not isinstance(tier, int):
            continue
        models.append(
            LLMModel(
                model_id=model_id,
                provider=provider,
                tier=tier,
                enabled=value.get("enabled") is True,
                free_confirmed=value.get("free_confirmed") is True,
                rpm=_optional_int(value.get("rpm")),
                rpd=_optional_int(value.get("rpd")),
                tpm=_optional_int(value.get("tpm")),
                tpd=_optional_int(value.get("tpd")),
            )
        )
    return tuple(sorted(models, key=lambda item: (item.tier, item.model_id)))


def eligible_models(raw: str) -> tuple[LLMModel, ...]:
    return tuple(model for model in parse_llm_models(raw) if model.enabled and model.free_confirmed)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
