from __future__ import annotations

import httpx
import pytest
from app.chat.turnstile import TurnstileUnavailable, verify_turnstile


async def test_turnstile_verification_posts_token_and_secret() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/turnstile/v0/siteverify"
        assert request.read().decode() == '{"secret":"secret","response":"token"}'
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await verify_turnstile("token", "secret", client=client)


async def test_turnstile_rejects_invalid_tokens() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"success": False}),
        )
    ) as client:
        assert not await verify_turnstile("invalid", "secret", client=client)


async def test_turnstile_reports_provider_failures() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(TurnstileUnavailable):
            await verify_turnstile("token", "secret", client=client)
