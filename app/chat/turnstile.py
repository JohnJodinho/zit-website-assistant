from __future__ import annotations

from typing import Protocol

import httpx

from app.obs.logging import get_logger

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileUnavailable(RuntimeError):
    pass


class _PostClient(Protocol):
    async def post(self, url: str, *, json: dict[str, str]) -> httpx.Response: ...


async def verify_turnstile(
    token: str,
    secret: str,
    *,
    client: _PostClient | None = None,
) -> bool:
    payload = {"secret": secret, "response": token}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=3.0) as http_client:
                response = await http_client.post(_SITEVERIFY_URL, json=payload)
        else:
            response = await client.post(_SITEVERIFY_URL, json=payload)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        get_logger("chat.turnstile").warning(
            "turnstile_verification_unavailable",
            error_type=type(exc).__name__,
        )
        raise TurnstileUnavailable from exc
    success = result.get("success") if isinstance(result, dict) else None
    if not isinstance(success, bool):
        get_logger("chat.turnstile").warning("turnstile_response_invalid")
        raise TurnstileUnavailable
    return success
