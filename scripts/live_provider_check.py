from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from app.chat.answer import answer_is_grounded
from app.chat.models import LLMModel, eligible_models
from app.chat.providers import (
    GeminiProvider,
    GroqProvider,
    ProviderError,
    StreamingProvider,
    Usage,
)
from app.config import get_settings
from app.search.hybrid import SearchHit
from pydantic import SecretStr

_PROMPT = (
    "Using only this context, write one short sentence telling visitors to contact "
    "ZIT Admissions for current course information. Do not invent a URL or phone number.\n"
    "Context: For current ZIT course information, visitors should contact ZIT Admissions."
)
_CONTEXT = SearchHit(
    chunk_key="live-check-context",
    doc_key="live-check-context",
    score=1.0,
    text="For current ZIT course information, visitors should contact ZIT Admissions.",
    vector_score=1.0,
    bm25_score=1.0,
)
_PROJECT_ID = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:12]
_CACHE_PATH = Path(tempfile.gettempdir()) / f"zit-assistant-live-{_PROJECT_ID}.json"
_PREFERRED_MODELS = {
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-3.5-flash-lite",
}


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
    rate_limited: bool = False


def _cache_key(provider: str, model: str) -> str:
    return hashlib.sha256(f"{provider}\n{model}\n{_PROMPT}".encode()).hexdigest()


def _load_cache() -> dict[str, CheckResult]:
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "live-check cache is invalid; refusing to repeat provider calls"
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimeError("live-check cache is invalid; refusing to repeat provider calls")
    try:
        return {key: CheckResult(**value) for key, value in raw.items()}
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "live-check cache is invalid; refusing to repeat provider calls"
        ) from exc


def _save_cache(cache: dict[str, CheckResult]) -> None:
    temporary_path = _CACHE_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({key: asdict(value) for key, value in cache.items()}, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary_path, _CACHE_PATH)


def _select_model(models: tuple[LLMModel, ...], provider: str) -> LLMModel | None:
    candidates = [model for model in models if model.provider == provider]
    preferred = _PREFERRED_MODELS[provider]
    return next(
        (model for model in candidates if model.model_id == preferred),
        candidates[0] if candidates else None,
    )


def _provider(provider_name: str, key: str) -> StreamingProvider:
    if provider_name == "groq":
        return GroqProvider(key)
    return GeminiProvider(key)


def _key_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    key = value.get_secret_value().strip()
    return key or None


def _target(
    provider_name: str,
    key: str | None,
    models: tuple[LLMModel, ...],
) -> tuple[LLMModel | None, str | None]:
    if key is None:
        return None, "missing_key"
    model = _select_model(models, provider_name)
    return (model, None) if model is not None else (None, "no_eligible_model")


async def _run_check(
    provider_name: str,
    model: LLMModel,
    key: str,
) -> tuple[CheckResult, bool]:
    provider = _provider(provider_name, key)
    fragments: list[str] = []
    usage: Usage | None = None
    failure: str | None = None
    rate_limited = False
    try:
        async for text, update in provider.stream(
            model=model.model_id,
            prompt=_PROMPT,
            max_output_tokens=80,
        ):
            if text:
                fragments.append(text)
            if update is not None and update.usage is not None:
                usage = update.usage
    except ProviderError as exc:
        failure = exc.error_class
        rate_limited = exc.status_code == 429
    except Exception as exc:
        failure = type(exc).__name__
    try:
        await provider.close()
    except Exception as exc:
        failure = failure or type(exc).__name__

    answer = "".join(fragments).strip()
    if failure is None and not answer:
        failure = "empty_answer"
    if failure is None and "admissions" not in answer.lower():
        failure = "answer_not_grounded"
    if failure is None and not answer_is_grounded(answer, [_CONTEXT], []):
        failure = "answer_not_grounded"
    if failure is None and (usage is None or usage.tokens_in <= 0 or usage.tokens_out <= 0):
        failure = "usage_missing"
    if failure is not None:
        return (
            CheckResult("FAIL", model.model_id, error=failure, rate_limited=rate_limited),
            rate_limited,
        )
    if usage is None:
        return CheckResult("FAIL", model.model_id, error="usage_missing"), rate_limited
    return (
        CheckResult("PASS", model.model_id, usage.tokens_in, usage.tokens_out),
        rate_limited,
    )


async def main() -> int:
    settings = get_settings()
    models = eligible_models(settings.llm_models)
    targets = (
        ("groq", _key_value(settings.groq_api_key)),
        ("gemini", _key_value(settings.google_ai_api_key)),
    )
    try:
        cache = _load_cache()
    except RuntimeError as exc:
        print(f"LIVE FAIL\t{exc}")
        return 1

    failed = False
    for provider_name, key in targets:
        model, reason = _target(provider_name, key, models)
        if reason == "missing_key":
            print(f"LIVE-{provider_name.upper()} SKIPPED\tprovider key missing")
            continue
        if reason is not None or model is None or key is None:
            print(f"LIVE-{provider_name.upper()} FAIL\t{reason or 'configuration_invalid'}")
            failed = True
            continue

        cache_key = _cache_key(provider_name, model.model_id)
        result = cache.get(cache_key)
        cached = result is not None
        rate_limited = result.rate_limited if result is not None else False
        if result is None:
            result, rate_limited = await _run_check(provider_name, model, key)
            cache[cache_key] = result
            _save_cache(cache)

        if result.status == "PASS":
            suffix = " cached" if cached else ""
            print(
                f"LIVE-{provider_name.upper()} PASS{suffix}\t"
                f"model={result.model} tokens_in={result.tokens_in} tokens_out={result.tokens_out}"
            )
        else:
            print(f"LIVE-{provider_name.upper()} FAIL\t{result.error or 'provider_check_failed'}")
            failed = True
        if rate_limited:
            print("LIVE STOPPED\trate limit received; no further live calls attempted")
            break

    if failed:
        print("LIVE FAIL")
        return 1
    print("LIVE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
